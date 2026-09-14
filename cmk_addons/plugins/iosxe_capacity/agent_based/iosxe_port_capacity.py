#!/usr/bin/env python3
"""Cisco IOS-XE physical port capacity.

Counts the front-panel ports of a Catalyst switch or stack, split into the
pools someone actually chooses from when they need a port, and reports how
many are in use.

Everything here comes from the SNMP session Checkmk already has with the
switch: no SSH, no credential, no scheduled job, no intermediate file.

--- how the pools are found ------------------------------------------------

A Catalyst names its interfaces <kind><member>/<slot>/<port>, and ifName
gives the short form: Gi1/0/1, Te3/1/2. All three fields carry information.

  member  which physical box in the stack. Capacity is counted per box,
          because that is what somebody walks up to and plugs into.
  slot    0 is the built-in front panel; anything else is a pluggable
          uplink module.
  kind    the cage type. Gi and Te are different pools even on the same
          box in the same slot.

That last point is not theoretical. On one stack this was built against,
member 3 is a 36x mGig + 12x 10G model: 36 Gi cages and 12 Te cages, all in
slot 0, all front panel. The 12 Te cages were 12 of 12 occupied while the Gi
cages sat at 64%. Folded into one number that is 35 of 48, 73%, and the fact
that not one free 10G port was left would not have shown anywhere.

--- why the ENTITY-MIB is consulted ----------------------------------------

The interface table cannot be trusted on its own. On a Catalyst with a
pluggable uplink bay, IOS-XE pre-creates interface names for every module
personality the bay accepts, whether or not that module is installed. One
stack advertises, in a single uplink slot, 4x Gi, 8x Te, 2x Fo and 2x Twe -
the NM-4G, NM-8X, NM-2Q and NM-2Y catalogues laid side by side, 16 names for
8 cages.

Nothing in the interface table separates them. A pre-created name carries the
same nominal ifHighSpeed, the same ifAdminStatus and the same ifOperStatus as
a real cage nobody has plugged into yet. ifConnectorPresent is documented for
exactly this question and is useless in practice: this hardware answers
"true" for every one of them, including the internal AppGigabitEthernet port,
which has no connector at all.

The ENTITY-MIB does separate them, but only if both classes are read:

  port(10)       a fixed port, and an SFP cage that has a transceiver in it.
                 Reading this class alone undercounts: on a stack whose three
                 uplink modules hold 4 cages each, it returns 1, 0 and 1 -
                 the number of optics fitted, not the number of cages. A pool
                 sized that way is 100% used by construction.
  container(5)   the cage itself, fitted or empty. This is what capacity
                 means for an SFP slot.

A position is real if it appears under either class. A pre-created name
appears under neither.

--- what is deliberately not used ------------------------------------------

ifHighSpeed. On mGig cages it reports the negotiated speed, not what the cage
can carry: the same Gi3/0 block reports 100 and 1000, and Te3/0 reports 5000
and 10000. Grouping by speed would scatter one physical pool across several
groups, and move a port between groups whenever a link renegotiated.

--- how the join is made ---------------------------------------------------

By name, because a container entity has no ifIndex to join on. Which name is
not settled across Cisco platforms: a Catalyst switch gives entPhysicalName
in the short form the interface table uses, "Te1/1/1", while a Catalyst 8000
router gives the long form, "TenGigabitEthernet0/0/1". So each interface is
offered under both of its own names - ifName and ifDescr - and matches if
either is known to the chassis.

The chassis side needs trimming too. A cage is named for the interface it
carries plus a word saying what it is, "Te1/1/1 Container", where the port
entity inside it is named "Te1/1/1" flat. An interface name never contains a
space, so the first token is what gets compared.

If nothing matches at all, the plugin falls back to the interface table
rather than report a switch with no ports, and says so in the service output.
Inflated capacity carrying a warning beats a confident zero.

--- scope ------------------------------------------------------------------

Built and verified against stackable Catalyst (9200/9300 class), where slot 0
is the front panel and slot 1 is the uplink module. On a modular chassis such
as a 9400, the middle field is a line-card slot and the access/uplink reading
does not hold. Such a device needs its own look at the data first.
"""

import re
from dataclasses import dataclass
from typing import Sequence

from cmk.agent_based.v2 import (
    CheckPlugin,
    CheckResult,
    DiscoveryResult,
    Metric,
    OIDEnd,
    Result,
    Service,
    SNMPSection,
    SNMPTree,
    State,
    StringTable,
    check_levels,
    contains,
)

# <kind><member>/<slot>/<port>, as ifName reports it: Gi1/0/1, Te3/1/2.
#
# Matching any alphabetic prefix and excluding the known non-front-panel ones
# is deliberate. Cisco adds an abbreviation with every new port speed, and an
# allowlist would silently drop ports on hardware nobody has racked yet -
# understating capacity, which is the direction that hurts. The logical
# interfaces do not have this three-field shape at all (Vl100, Po1, Nu0,
# StackPort1, StackSub-St1-1, Gi0/0), and a sub-interface such as Gi0/0/0.100
# fails the anchor, so the shape does most of the filtering.
_PHYSICAL_PORT = re.compile(r"^([A-Za-z]+)(\d+)/(\d+)/(\d+)$")

# AppGigabitEthernet is the internal app-hosting port. It has the three-field
# shape but no cage on the front panel.
_NOT_FRONT_PANEL = frozenset({"Ap"})

# The built-in front panel. Any other slot is a pluggable uplink module.
_BUILTIN_SLOT = 0

# ENTITY-MIB entPhysicalClass: container(5) is the cage, port(10) is a fixed
# port or a fitted transceiver. See the module docstring for why both matter.
_PHYSICAL_ENTITY_CLASSES = frozenset({"5", "10"})


@dataclass(frozen=True)
class Port:
    kind: str
    member: int
    slot: int
    number: int
    admin_up: bool
    oper_up: bool

    @property
    def role(self) -> str:
        return "access" if self.slot == _BUILTIN_SLOT else "uplink"

    @property
    def item(self) -> str:
        return f"{self.member} {self.kind} {self.role}"


@dataclass(frozen=True)
class Section:
    ports: list[Port]
    # False when the physical inventory could not be used, so the counts come
    # from the interface table and may include uplink module positions that
    # are not populated.
    inventory_used: bool


def _physical_positions(entity_table: StringTable) -> set[str]:
    """Names of front-panel positions the chassis says physically exist.

    A cage entity is named for the interface it carries plus a word saying
    what it is - "Te1/1/1 Container" - while the port entity inside it is
    named "Te1/1/1" flat. An interface name never contains a space, so the
    first token is taken as well as the whole string, and both are offered
    for matching.
    """
    positions: set[str] = set()
    for _index, entity_class, name in entity_table:
        if entity_class not in _PHYSICAL_ENTITY_CLASSES:
            continue
        head = name.split(" ")[0] if name else ""
        if head:
            positions.add(head)
    return positions


def parse_iosxe_port_capacity(string_table: Sequence[StringTable]) -> Section:
    interface_by_index = {
        index: (descr, admin, oper) for index, descr, admin, oper in string_table[0]
    }
    physical = _physical_positions(string_table[2])

    candidates: list[tuple[tuple[str, str], Port]] = []
    for index, name in string_table[1]:
        matched = _PHYSICAL_PORT.match(name)
        if not matched:
            continue

        kind = matched.group(1)
        if kind in _NOT_FRONT_PANEL:
            continue

        descr, admin, oper = interface_by_index.get(index, ("", "", ""))
        candidates.append(
            (
                (name, descr),
                Port(
                    kind=kind,
                    member=int(matched.group(2)),
                    slot=int(matched.group(3)),
                    number=int(matched.group(4)),
                    admin_up=admin == "1",
                    oper_up=oper == "1",
                ),
            )
        )

    confirmed = [
        port for names, port in candidates if not physical.isdisjoint(names)
    ]
    if confirmed:
        return Section(ports=confirmed, inventory_used=True)

    # Either the device has no usable inventory, or it names its entities in a
    # way this join does not recognise. Keep every port rather than report an
    # empty switch, and let the check say the counts are unverified.
    return Section(ports=[port for _names, port in candidates], inventory_used=False)


snmp_section_iosxe_port_capacity = SNMPSection(
    name="iosxe_port_capacity",
    # sysDescr reads "Cisco IOS Software [...], Catalyst L3 Switch Software
    # (CAT9K_IOSXE)". There is no hyphen in the string on the device, whatever
    # the product is called in the documentation.
    detect=contains(".1.3.6.1.2.1.1.1.0", "IOSXE"),
    fetch=[
        # ifDescr (.2), ifAdminStatus (.7), ifOperStatus (.8), by ifIndex.
        # ifDescr is fetched only to give the ENTITY-MIB join a second name to
        # match against; the port's identity comes from ifName.
        SNMPTree(base=".1.3.6.1.2.1.2.2.1", oids=[OIDEnd(), "2", "7", "8"]),
        # ifName (.1), keyed by ifIndex
        SNMPTree(base=".1.3.6.1.2.1.31.1.1.1", oids=[OIDEnd(), "1"]),
        # ENTITY-MIB entPhysicalClass (.5) and entPhysicalName (.7)
        SNMPTree(base=".1.3.6.1.2.1.47.1.1.1.1", oids=[OIDEnd(), "5", "7"]),
    ],
    parse_function=parse_iosxe_port_capacity,
)


def _group_ports(ports: Sequence[Port]) -> dict[str, list[Port]]:
    grouped: dict[str, list[Port]] = {}
    for port in ports:
        grouped.setdefault(port.item, []).append(port)
    return grouped


def _sort_key(item: str) -> tuple[int, str, str]:
    member, kind, role = item.split(" ")
    return int(member), kind, role


def discover_iosxe_port_capacity(section: Section) -> DiscoveryResult:
    for item in sorted(_group_ports(section.ports), key=_sort_key):
        yield Service(item=item)


def check_iosxe_port_capacity(
    item: str, params: dict, section: Section
) -> CheckResult:
    ports = _group_ports(section.ports).get(item)
    if not ports:
        return

    total = len(ports)
    in_use = sum(1 for p in ports if p.oper_up)
    free = total - in_use
    shut = sum(1 for p in ports if not p.admin_up)

    yield Result(state=State.OK, summary=f"{total} ports, {in_use} in use, {free} free")

    yield from check_levels(
        in_use / total * 100.0,
        levels_upper=params["levels_upper"],
        metric_name="iosxe_port_utilization",
        label="Capacity used",
        render_func=lambda value: f"{value:.1f}%",
        boundaries=(0.0, 100.0),
    )

    yield Metric("iosxe_ports_total", total)
    yield Metric("iosxe_ports_in_use", in_use, boundaries=(0, total))
    yield Metric("iosxe_ports_free", free, boundaries=(0, total))

    if shut:
        yield Result(
            state=State.OK,
            notice=f"{shut} port(s) administratively shut, counted as available",
        )

    if not section.inventory_used:
        yield Result(
            state=State.OK,
            notice=(
                "Physical inventory unusable; counts come from the interface "
                "table and may include uplink module positions that are not "
                "populated"
            ),
        )


check_plugin_iosxe_port_capacity = CheckPlugin(
    name="iosxe_port_capacity",
    # "Switch" spells out what the leading number is: the stack member.
    service_name="Port capacity Switch %s",
    discovery_function=discover_iosxe_port_capacity,
    check_function=check_iosxe_port_capacity,
    check_ruleset_name="iosxe_port_capacity",
    check_default_parameters={"levels_upper": ("fixed", (80.0, 90.0))},
)
