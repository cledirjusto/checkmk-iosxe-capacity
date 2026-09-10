"""Regression tests built from real snmpwalks of two Catalyst stacks.

The numbers are not invented.

The access stack has three members: members 1 and 2 are 48-port Gi switches
with a 4-cage 10G uplink module, member 3 is a 36x mGig + 12x 10G model with
the same uplink module. 156 front-panel positions.

The edge stack has two members, 24x 10G each, with an 8-cage uplink module.
It is why the ENTITY-MIB is consulted at all: its interface table advertises
four uplink module personalities at once, 16 names per member where 8 cages
exist.

Between them the two stacks pin both halves of the entity rule. The uplink
cages of the access stack hold 1, 0 and 1 transceivers, so reading only
entPhysicalClass port(10) would size those pools at 1, 0 and 1 - fully used
by construction. Reading container(5) as well gives 4, 4 and 4.

If a change makes these fail, the change is wrong.
"""

import re

import iosxe_port_capacity as plugin

# ifDescr spells out what ifName abbreviates. A Catalyst switch names its
# ENTITY-MIB entries the short way and a Catalyst 8000 router the long way, so
# the plugin matches against both and these tests exercise each.
_LONG_FORM = {
    "Gi": "GigabitEthernet",
    "Te": "TenGigabitEthernet",
    "Fo": "FortyGigabitEthernet",
    "Twe": "TwentyFiveGigE",
}


def _descr(name):
    kind, rest = re.match(r"^([A-Za-z]+)(.*)$", name).groups()
    return _LONG_FORM.get(kind, kind) + rest

# (module, ifOperStatus, ifAdminStatus, count, entity class)
#
# Entity class is what the ENTITY-MIB says about those positions: "10" for a
# fixed port, "5" for an SFP cage, None for a name IOS-XE pre-created for a
# module that is not installed.
#
# The ifHighSpeed each block reported is noted alongside. It is not fed to the
# plugin, on purpose: on mGig cages it is the negotiated speed, so a single
# physical pool reports several values.
ACCESS_STACK = [
    ("Gi1/0", "1", "1", 11, "10"),  # 1000
    ("Gi1/0", "2", "1", 34, "10"),  # 1000
    ("Gi1/0", "1", "1", 2, "10"),   # 100
    ("Gi1/0", "2", "1", 1, "10"),   # 100
    ("Gi2/0", "1", "1", 20, "10"),  # 1000
    ("Gi2/0", "2", "1", 27, "10"),  # 1000
    ("Gi2/0", "1", "1", 1, "10"),   # 100
    ("Gi3/0", "1", "1", 22, "10"),  # 1000
    ("Gi3/0", "2", "1", 13, "10"),  # 1000
    ("Gi3/0", "1", "1", 1, "10"),   # 100
    ("Te1/1", "1", "1", 1, "5"),    # 10000, cage with an optic in it
    ("Te1/1", "2", "1", 3, "5"),    # 10000, empty cages
    ("Te2/1", "2", "1", 4, "5"),    # 10000, module with nothing fitted
    ("Te3/0", "1", "1", 9, "10"),   # 10000
    ("Te3/0", "1", "1", 3, "10"),   # 5000
    ("Te3/1", "1", "1", 1, "5"),    # 10000
    ("Te3/1", "2", "1", 3, "5"),    # 10000
]

ACCESS_EXPECTED = {
    "1 Gi access": (48, 13),
    "1 Te uplink": (4, 1),
    "2 Gi access": (48, 21),
    "2 Te uplink": (4, 0),
    "3 Gi access": (36, 23),
    "3 Te access": (12, 12),
    "3 Te uplink": (4, 1),
}

EDGE_STACK = [
    ("Te1/0", "2", "1", 4, "10"),
    ("Te1/0", "2", "2", 19, "10"),
    ("Te1/0", "1", "1", 1, "10"),
    ("Te1/1", "1", "1", 4, "5"),     # cages holding optics
    ("Te1/1", "2", "1", 4, "5"),     # cages of the same module, empty
    ("Gi1/1", "2", "1", 4, None),    # NM-4G personality, no module fitted
    ("Fo1/1", "2", "1", 2, None),    # NM-2Q personality
    ("Twe1/1", "2", "1", 2, None),   # NM-2Y personality
    ("Te2/0", "2", "2", 22, "10"),
    ("Te2/0", "1", "1", 2, "10"),
    ("Te2/1", "1", "1", 4, "5"),
    ("Te2/1", "2", "1", 4, "5"),
    ("Gi2/1", "2", "1", 4, None),
    ("Fo2/1", "2", "1", 2, None),
    ("Twe2/1", "2", "1", 2, None),
]

EDGE_EXPECTED = {
    "1 Te access": (24, 1),
    "1 Te uplink": (8, 4),
    "2 Te access": (24, 2),
    "2 Te uplink": (8, 4),
}


def _walk(blocks, with_inventory=True, entity_names="short"):
    """Build the three SNMP tables the section fetches."""
    status, names, entities = [], [], []
    next_port: dict[str, int] = {}
    index = 0
    entity_index = 1000  # deliberately unrelated to ifIndex

    # A chassis and a stack member container, to prove that entity classes
    # and names which are not front-panel positions are ignored.
    entities.append(["1", "3", "Chassis"])
    entities.append(["2", "5", "Switch 1"])

    for module, oper, admin, count, entity_class in blocks:
        for _ in range(count):
            index += 1
            port = next_port.get(module, 0) + 1
            next_port[module] = port
            name = f"{module}/{port}"
            status.append([str(index), _descr(name), admin, oper])
            names.append([str(index), name])
            if entity_class and with_inventory:
                entity_index += 1
                entity_name = _descr(name) if entity_names == "long" else name
                if entity_class == "5":
                    # A cage is named for what it carries plus what it is.
                    # Missing this suffix is what made an earlier build size
                    # every uplink module by the optics fitted in it.
                    entity_name += " Container"
                entities.append([str(entity_index), entity_class, entity_name])

    if not with_inventory:
        entities = []
    return [status, names, entities]


def _section(blocks, with_inventory=True, entity_names="short"):
    return plugin.parse_iosxe_port_capacity(
        _walk(blocks, with_inventory, entity_names)
    )


def _grouped(blocks, with_inventory=True, entity_names="short"):
    return plugin._group_ports(_section(blocks, with_inventory, entity_names).ports)


def _counts(groups):
    return {
        item: (len(ports), sum(1 for p in ports if p.oper_up))
        for item, ports in groups.items()
    }


def test_parses_only_front_panel_ports():
    names = [
        "Gi1/0/1",        # front panel
        "Te3/1/2",        # uplink module
        "Ap1/0/1",        # AppGigabitEthernet, internal app hosting
        "Gi0/0",          # out-of-band management, only two fields
        "Vl100",          # SVI
        "Po1",            # port-channel
        "Nu0",            # Null0
        "StackPort1",     # stack fabric
        "StackSub-St1-1", # stack fabric
        "Gi0/0/0.100",    # sub-interface
    ]
    status = [[str(i), _descr(n), "1", "1"] for i, n in enumerate(names, start=1)]
    name_table = [[str(i), n] for i, n in enumerate(names, start=1)]
    section = plugin.parse_iosxe_port_capacity([status, name_table, []])
    assert sorted(p.item for p in section.ports) == ["1 Gi access", "3 Te uplink"]


def test_access_stack_matches_the_walk():
    assert _counts(_grouped(ACCESS_STACK)) == ACCESS_EXPECTED


def test_access_stack_every_position_lands_in_exactly_one_pool():
    assert sum(len(p) for p in _grouped(ACCESS_STACK).values()) == 156


def test_empty_sfp_cages_still_count_as_capacity():
    """Reading only entPhysicalClass port(10) would size these pools by the
    number of transceivers fitted - 1, 0 and 1 - making them permanently
    full. The cages are the capacity, fitted or not."""
    groups = _grouped(ACCESS_STACK)
    assert len(groups["1 Te uplink"]) == 4
    assert len(groups["2 Te uplink"]) == 4  # module with nothing plugged in
    assert sum(1 for p in groups["2 Te uplink"] if p.oper_up) == 0


def test_ten_gig_front_panel_ports_are_access_not_uplink():
    """Te3/0/* sit in the front panel of member 3, next to its Gi cages.

    Grouping by name prefix or by speed would file them as uplinks and invent
    uplink capacity that does not exist."""
    groups = _grouped(ACCESS_STACK)
    assert len(groups["3 Te access"]) == 12
    assert len(groups["3 Te uplink"]) == 4
    assert all(p.slot == 0 for p in groups["3 Te access"])
    assert all(p.slot == 1 for p in groups["3 Te uplink"])


def test_a_full_pool_is_visible_on_its_own():
    """The reason pools are split per cage type rather than per member."""
    groups = _grouped(ACCESS_STACK)
    assert all(p.oper_up for p in groups["3 Te access"])

    member_3_front = [
        p for item, ports in groups.items() if item.startswith("3 ")
        for p in ports if p.slot == 0
    ]
    merged = sum(1 for p in member_3_front if p.oper_up) / len(member_3_front)
    assert merged < 0.8  # would have read OK, hiding a pool with nothing left


def test_uninstalled_module_personalities_are_not_counted():
    """The edge stack advertises 16 uplink names per member, 8 cages exist."""
    assert _counts(_grouped(EDGE_STACK)) == EDGE_EXPECTED


def test_without_the_entity_mib_the_phantom_positions_would_be_counted():
    """Pins what the join is buying, so removing it fails loudly."""
    unfiltered = _counts(_grouped(EDGE_STACK, with_inventory=False))
    assert unfiltered["1 Te uplink"] == (8, 4)
    assert unfiltered["1 Gi uplink"] == (4, 0)
    assert unfiltered["1 Fo uplink"] == (2, 0)
    assert unfiltered["1 Twe uplink"] == (2, 0)


def test_unusable_inventory_falls_back_instead_of_reporting_nothing():
    section = _section(ACCESS_STACK, with_inventory=False)
    assert section.inventory_used is False
    assert len(section.ports) == 156


def test_long_form_entity_names_are_matched_through_ifdescr():
    """A Catalyst 8000 names entities "TenGigabitEthernet0/0/1" where the
    interface table says "Te0/0/1". Matching only ifName would drop every
    port on such a device and silently fall back."""
    section = _section(EDGE_STACK, entity_names="long")
    assert section.inventory_used is True
    assert _counts(plugin._group_ports(section.ports)) == EDGE_EXPECTED


def test_entity_names_that_match_neither_form_fall_back():
    status = [["1", "GigabitEthernet1/0/1", "1", "1"], ["2", "GigabitEthernet1/0/2", "1", "1"]]
    names = [["1", "Gi1/0/1"], ["2", "Gi1/0/2"]]
    entities = [["1001", "5", "subslot 0/0"], ["1002", "10", "NME"]]
    section = plugin.parse_iosxe_port_capacity([status, names, entities])
    assert section.inventory_used is False
    assert len(section.ports) == 2


def test_usable_inventory_is_recorded():
    assert _section(ACCESS_STACK).inventory_used is True


def test_admin_shut_ports_are_still_counted_in_the_pool():
    status = [
        ["1", "GigabitEthernet1/0/1", "2", "2"],
        ["2", "GigabitEthernet1/0/2", "1", "1"],
    ]
    names = [["1", "Gi1/0/1"], ["2", "Gi1/0/2"]]
    section = plugin.parse_iosxe_port_capacity([status, names, []])
    assert [p.admin_up for p in section.ports] == [False, True]
    assert [p.oper_up for p in section.ports] == [False, True]


def test_discovery_yields_one_service_per_pool_in_stack_order():
    section = _section(ACCESS_STACK)
    items = [s.item for s in plugin.discover_iosxe_port_capacity(section)]
    assert items == [
        "1 Gi access",
        "1 Te uplink",
        "2 Gi access",
        "2 Te uplink",
        "3 Gi access",
        "3 Te access",
        "3 Te uplink",
    ]


def test_unknown_port_type_is_counted_rather_than_dropped():
    """A future abbreviation must not silently understate capacity."""
    status = [["1", "XyGigabitEthernet2/0/7", "1", "1"]]
    names = [["1", "Xy2/0/7"]]
    section = plugin.parse_iosxe_port_capacity([status, names, []])
    assert [p.item for p in section.ports] == ["2 Xy access"]
