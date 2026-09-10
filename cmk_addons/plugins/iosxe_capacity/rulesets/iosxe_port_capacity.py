#!/usr/bin/env python3
"""WATO ruleset for the IOS-XE port capacity check.

Written against cmk.rulesets.v1, the API that replaces the legacy GUI
extensions removed in 2.4.0.
"""

from cmk.rulesets.v1 import Help, Title
from cmk.rulesets.v1.form_specs import (
    DefaultValue,
    DictElement,
    Dictionary,
    LevelDirection,
    Percentage,
    SimpleLevels,
)
from cmk.rulesets.v1.rule_specs import CheckParameters, HostAndItemCondition, Topic


def _parameter_form() -> Dictionary:
    return Dictionary(
        elements={
            "levels_upper": DictElement(
                required=True,
                parameter_form=SimpleLevels(
                    title=Title("Levels on used port capacity"),
                    help_text=Help(
                        "Percentage of the front-panel ports in this pool whose "
                        "operational status is up. A pool is one cage type on one "
                        "stack member, in either the built-in front panel or an "
                        "uplink module. Ports that are administratively shut are "
                        "counted as available, not as used."
                    ),
                    form_spec_template=Percentage(),
                    level_direction=LevelDirection.UPPER,
                    prefill_fixed_levels=DefaultValue((80.0, 90.0)),
                ),
            ),
        },
    )


rule_spec_iosxe_port_capacity = CheckParameters(
    name="iosxe_port_capacity",
    title=Title("Cisco IOS-XE port capacity"),
    topic=Topic.NETWORKING,
    parameter_form=_parameter_form,
    condition=HostAndItemCondition(item_title=Title("Port pool")),
)
