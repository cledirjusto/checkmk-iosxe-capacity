# iosxe-port-capacity

A Checkmk check plugin that reports physical port capacity on Cisco Catalyst
switches running IOS-XE, over the SNMP session Checkmk already has with them.

No agent plugin, no MRPE entry, no SSH, no credential, no scheduled job, no
intermediate file.

## What it does

Discovers one service per port pool. A pool is one cage type, on one stack
member, in either the built-in front panel or an uplink module:

```
Port capacity 1 Gi access    48 ports, 13 in use, 35 free, Capacity used: 27.1%
Port capacity 1 Te uplink     4 ports,  1 in use,  3 free, Capacity used: 25.0%
Port capacity 3 Gi access    36 ports, 23 in use, 13 free, Capacity used: 63.9%
Port capacity 3 Te access    12 ports, 12 in use,  0 free, Capacity used: 100.0%
Port capacity 3 Te uplink     4 ports,  1 in use,  3 free, Capacity used: 25.0%
```

- **Capacity is counted per physical box.** A stack member is what somebody
  walks up to and plugs into, so each member gets its own pools.
- **Cage types are separate pools.** On a 36x mGig + 12x 10G member, the 10G
  half can be completely full while the whole member reads 73%. Splitting
  them is the difference between seeing that and not.
- **Access and uplink are separate pools.** Slot 0 is the built-in front
  panel; any other slot is a pluggable uplink module.
- **"In use" means `ifOperStatus == up`.** Administratively shut ports count
  as available and are reported separately.
- **`ifHighSpeed` is not used.** On mGig cages it reports the negotiated
  speed, not the cage, so grouping by it would split one physical pool and
  move ports between pools on renegotiation.
- **Logical and internal interfaces are excluded**: `Vl`, `Po`, `Nu`,
  `StackPort`, `StackSub`, the `Gi0/0` management port, sub-interfaces, and
  `AppGigabitEthernet`.
- **Module personalities that are not installed are excluded.** IOS-XE
  pre-creates interface names for every uplink module a bay accepts: one
  stack advertises 4x Gi, 8x Te, 2x Fo and 2x Twe in a single slot that
  holds 8 cages. Nothing in the interface table separates those from a real
  cage nobody has plugged into, and `ifConnectorPresent` answers "true" for
  all of them, so the plugin reads the ENTITY-MIB. Both classes matter:
  `port(10)` covers fixed ports and cages with a transceiver fitted, while
  `container(5)` is the cage itself, fitted or empty. Reading only `port(10)`
  would size an SFP pool by the optics in it and report every uplink module
  as permanently full.
- **The inventory is joined on either name.** A container entity has no
  ifIndex, so the join is by name, and Cisco is not consistent about which
  name: a Catalyst switch reports `entPhysicalName` as `Te1/1/1`, a Catalyst
  8000 router as `TenGigabitEthernet0/0/1`. Each interface is offered under
  both `ifName` and `ifDescr` and matches on either. If nothing matches at
  all, the plugin falls back to the interface table rather than report a
  switch with no ports, and says so in the service output.

Levels are set in WATO, on percentage used, defaulting to 80% / 90%.

## Scope

Built and verified against stackable Catalyst (9200/9300 class), where slot 0
is the front panel and slot 1 is the uplink module. On a modular chassis such
as a 9400 the middle field is a line-card slot and the access/uplink reading
does not hold; that hardware needs its own look at the data first.

## Requirements

Checkmk 2.3.0 or newer. Uses `cmk.agent_based.v2`, `cmk.rulesets.v1` and
`cmk.graphing.v1`, so it is unaffected by the plugin API removals in 2.4.0.

## Install

```bash
DEST=/omd/sites/<site>/local/lib/python3/cmk_addons/plugins
mkdir -p "$DEST"
cp -r cmk_addons/plugins/iosxe_capacity "$DEST/"
chown -R <site>:<site> "$DEST/iosxe_capacity"

omd restart <site> apache
su - <site> -c 'cmk -L' | grep iosxe_port_capacity
```

Then run service discovery on one switch and check the numbers before rolling
out to the rest. The check that matters: the pools of a member must sum to
that member's front-panel port count.

## Tests

Run without a Checkmk installation — `tests/conftest.py` stubs the plugin API.

```bash
python3 -m pytest tests/ -v
```

The regression test encodes a real snmpwalk of a three-member stack, 156
front-panel ports across seven pools.

## Layout

```
cmk_addons/plugins/iosxe_capacity/
  agent_based/iosxe_port_capacity.py   SNMP section, discovery, check
  rulesets/iosxe_port_capacity.py      WATO levels
  graphing/iosxe_port_capacity.py      metrics, graph, perf-o-meter
tests/                                 runs anywhere
```

## License

GPL-2.0. See [LICENSE](LICENSE).
