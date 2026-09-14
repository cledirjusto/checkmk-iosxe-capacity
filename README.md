# Cisco Catalyst port capacity over SNMP – Checkmk extension

[![License: GPL v2](https://img.shields.io/badge/License-GPL_v2-blue.svg)](LICENSE)
![Checkmk 2.3+](https://img.shields.io/badge/Checkmk-2.3%2B-green)

A Checkmk check plug-in that counts the free physical ports of a Catalyst
switch or stack running IOS-XE, per stack member and per cage type.

It reads three standard SNMP tables over the session Checkmk already has with
the switch: `ifTable` and `ifXTable` from the IF-MIB, and `entPhysicalTable`
from the ENTITY-MIB. It adds no agent plug-in, no MRPE entry and no credential
of its own, and writes nothing to the device. Installing the package and running
a service discovery is the full procedure.

This is capacity, not fault state. Checkmk's interface checks already report the
status of each port. These services report how many positions of each kind
remain in the chassis.

Verified against Catalyst 9000 stacks on IOS-XE, including a three-member stack
whose members are different models, and an eight-cage uplink module. Uses only
plug-in APIs that are identical on 2.3, 2.4 and 2.5.

## Services

One service per **port pool**. A pool is one cage type, on one stack member, in
either the built-in front panel or an uplink module:

```
Port capacity Switch 1 Gi access    48 ports, 13 in use, 35 free, Capacity used: 27.1%
Port capacity Switch 1 Te uplink     4 ports,  1 in use,  3 free, Capacity used: 25.0%
Port capacity Switch 2 Gi access    48 ports, 21 in use, 27 free, Capacity used: 43.8%
Port capacity Switch 3 Gi access    36 ports, 23 in use, 13 free, Capacity used: 63.9%
Port capacity Switch 3 Te access    12 ports, 12 in use,  0 free, Capacity used: 100.0%
Port capacity Switch 3 Te uplink     4 ports,  1 in use,  3 free, Capacity used: 25.0%
```

The item is `<member> <cage type> <access|uplink>`. Each service carries four
metrics — ports in the pool, in use, free, and percentage used — a stacked
graph of used against free, and a perf-o-meter on the percentage.

Why the split is that shape:

* **Per stack member**, because a member is what somebody walks up to and plugs
  into. A free port in the next box up is not a free port here.
* **Per cage type**, because a 36x mGig + 12x 10G member can be 100% out of 10G
  cages while the member as a whole reads 73%. Merged into one number, "no 10G
  port left" appears nowhere.
* **Access apart from uplink**, because slot 0 is the built-in front panel and
  any other slot is a pluggable module. They are not interchangeable.

"In use" means `ifOperStatus` is up. A port that is administratively shut counts
as **available**, and is reported separately in the service details, because
someone can turn it on.

## Requirements

* Checkmk 2.3.0 or newer. Raw, Pro/Enterprise and Cloud editions.
* The switch already monitored over SNMP (v2c or v3), with the standard
  `IF-MIB` and `ENTITY-MIB` readable. Both are in the default view of every
  IOS-XE image; no custom SNMP view is needed.
* Nothing on the switch itself. The plug-in only reads.

Discovery is automatic on any host whose `sysDescr` contains `IOSXE`. A Catalyst
8000 router reports `X86_64_LINUX_IOSD-UNIVERSALK9-M` with no `IOSXE` token, so
routers are left alone.

## Installation

1. Download `iosxe_capacity-<version>.mkp` from the
   [releases page](../../releases).
2. Install it on the central site:

   ```
   OMD[mysite]:~$ mkp add iosxe_capacity-1.1.0.mkp
   OMD[mysite]:~$ mkp enable iosxe_capacity 1.1.0
   ```

   or use *Setup → Maintenance → Extension packages* in the commercial
   editions. In a distributed setup, upload it in the GUI and activate: a
   package operation on the command line writes no WATO change, so remote sites
   never receive it.
3. Restart Apache so the ruleset and the graphs show up: `omd restart apache`
   (once, after installation).
4. Check that it loaded: `cmk -L | grep iosxe_port_capacity`, or
   `cmk-validate-plugins`.

## Configuration

### 1. Discover the services

Run a service discovery on one switch first:

```
OMD[mysite]:~$ cmk --check-discovery <hostname>
```

Then look at the numbers before rolling out to the rest. **The check that
matters: the pools of a member must add up to that member's front-panel port
count.** A 48-port member with an uplink module should read 48 + the cages on
the module, not 48 + every cage type the bay would accept. If it reads high, see
*Reporting a problem* below.

### 2. Set the thresholds (optional)

*Setup → Services → Service monitoring rules → Networking → Cisco IOS-XE port
capacity*.

Levels are on the percentage of the pool in use, defaulting to **80% warning,
90% critical**. They can be set per host and per pool, which is usually what you
want: 90% of a 48-port access pool is five free ports, 90% of a 4-cage uplink
pool is nothing sensible. Give the uplink pools their own rule.

## How it works

Three SNMP tables, on the session Checkmk already has:

| OID | Table | Used for |
| --- | --- | --- |
| `.1.3.6.1.2.1.31.1.1.1.1` | `ifName` | The port's identity: `Gi1/0/1`, `Te3/1/2` |
| `.1.3.6.1.2.1.2.2.1` | `ifDescr`, `ifAdminStatus`, `ifOperStatus` | Occupancy, and a second name for the join below |
| `.1.3.6.1.2.1.47.1.1.1.1` | `entPhysicalClass`, `entPhysicalName` | Which positions physically exist |

`ifName` gives the abbreviated form, and all three of its fields carry
information: `<kind><member>/<slot>/<port>`. Member is the box, slot 0 is the
front panel, and the letter prefix is the cage type. That is the whole grouping
rule.

**What is excluded.** Anything that is not a front-panel position:
`Vl`, `Po`, `Nu`, `StackPort`, `StackSub`, the two-field `Gi0/0` management
port and sub-interfaces all fail the `x1/0/1` shape; `AppGigabitEthernet` has
the shape but is an internal app-hosting port, and is excluded by name. The
prefix is deliberately **not** an allowlist — Cisco adds an abbreviation with
every new speed, and dropping an unknown prefix would understate capacity, which
is the direction that hurts.

**What is not used: `ifHighSpeed`.** On mGig cages it reports the negotiated
speed rather than the cage, so the same `Gi3/0` block reports 100 and 1000 and
`Te3/0` reports 5000 and 10000. Grouping by it would scatter one physical pool
across several and move a port between pools whenever a link renegotiated.

**Why the ENTITY-MIB is read.** This is the part that makes the numbers correct.
IOS-XE pre-creates interface names for every module personality an uplink bay
accepts, installed or not: one stack advertises 4x `Gi`, 8x `Te`, 2x `Fo` and 2x
`Twe` in a single slot that holds **eight** cages — sixteen names for eight
positions. Nothing in the interface table separates them. A pre-created name has
the same nominal `ifHighSpeed`, `ifAdminStatus` and `ifOperStatus` as a real
cage nobody has plugged into, and `ifConnectorPresent` — documented for exactly
this question — answers "true" for all of them, including the internal port that
has no connector at all.

The ENTITY-MIB does separate them, but only with **both** classes read:

* `port(10)` is a fixed port, and an SFP cage with a transceiver fitted. Alone,
  it sizes a pool by the optics in it: three 4-cage uplink modules holding 1, 0
  and 1 optic come out as pools of 1, 0 and 1 — permanently 100% used, with one
  pool missing entirely.
* `container(5)` is the cage itself, fitted or empty. That is what capacity means
  for an SFP slot.

A position is real if it appears under either class. A pre-created name appears
under neither.

**The join is by name**, because a container entity has no `ifIndex`. Cisco is
not consistent about which name: a Catalyst switch reports `entPhysicalName` as
`Te1/1/1`, a Catalyst 8000 router as `TenGigabitEthernet0/0/1`. So each
interface is offered under both `ifName` and `ifDescr` and matches on either.
The chassis side needs trimming too — a cage is named `Te1/1/1 Container` while
the port entity inside it is `Te1/1/1` flat — so the first whitespace token is
compared.

If the join matches nothing at all, the plug-in keeps every interface-table port
rather than report a switch with no ports, and **says so in the service
details**. Inflated capacity carrying a warning beats a confident zero.

## Scope

Built and verified against **stackable Catalyst, 9200/9300 class**, where slot 0
is the front panel and slot 1 is the uplink module.

On a **modular chassis such as a 9400** the middle field is a line-card slot, so
the access/uplink reading does not hold and the pools would be labelled
misleadingly. The plug-in will discover services there because the `sysDescr`
matches; do not trust them without looking at the data first. Open an issue with
a walk and it can be handled properly.

## Reporting a problem

If a pool is sized wrong — most likely too large on a host with an uplink module
— what is useful in an issue is not a description, it is what the switch
actually replied:

```
snmpwalk -v2c -c <community> <host> .1.3.6.1.2.1.31.1.1.1.1   > ifname.walk
snmpwalk -v2c -c <community> <host> .1.3.6.1.2.1.47.1.1.1.1.5 > entclass.walk
snmpwalk -v2c -c <community> <host> .1.3.6.1.2.1.47.1.1.1.1.7 > entname.walk
```

Attach the **raw lines**, not a summary of them. Entity names carry a trailing
word (`Te1/1/1 Container`), and any filter that takes the first field silently
hides exactly the difference that matters here. Please also include the
`sysDescr` (`.1.3.6.1.2.1.1.1.0`) and the model of each stack member.

The walks contain interface names, entity names and the software version. They
do not contain addresses, communities or configuration.

## Development

The repository mirrors the site layout, so the tree under `cmk_addons/` can be
copied 1:1 into `~/local/lib/python3/cmk_addons/` of a site:

```
cmk_addons/plugins/iosxe_capacity/
  agent_based/iosxe_port_capacity.py   SNMP section, discovery, check
  rulesets/iosxe_port_capacity.py      WATO levels
  graphing/iosxe_port_capacity.py      metrics, graph, perf-o-meter
tests/                                 runs anywhere
```

Tests run without a Checkmk installation — `tests/conftest.py` stubs the
plug-in API:

```
python3 -m pytest tests/ -v
```

They encode a real snmpwalk of a three-member stack: 156 front-panel ports
across seven pools, one member of a different model from the other two. Two of
them exist specifically to pin the ENTITY-MIB behaviour — one asserts that an
uplink module with **no optics fitted** still reports four positions, the other
pins what the interface table alone would have counted, so a regression shows up
as a number rather than as a silently smaller pool.

There are 15 tests. To release, build the `.mkp` on a site with `mkp package`,
tag `v<version>`, and attach the package to the GitHub release.

## Compatibility notes

* Uses only `cmk.agent_based.v2`, `cmk.rulesets.v1` and `cmk.graphing.v1`, so it
  is unaffected by the legacy plug-in API removals in 2.4.0 and needs no change
  on 2.5.
* It does not conflict with the `cisco_*` and `if64` checks shipped with
  Checkmk: different plug-in family, different service names, and by design
  different data. Run it alongside the interface checks.

## License

GNU General Public License v2 (GPL-2.0-or-later) – see [LICENSE](LICENSE).
Checkmk plug-in APIs are GPL v2 licensed, so extensions published on the Checkmk
Exchange are subject to the same license.

Cisco, Catalyst and IOS-XE are trademarks of Cisco Systems, Inc. This project is
not affiliated with or endorsed by Cisco Systems or Checkmk GmbH.
