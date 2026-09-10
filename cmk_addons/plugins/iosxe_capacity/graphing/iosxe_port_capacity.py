#!/usr/bin/env python3
"""Metrics, graph and perf-o-meter for the IOS-XE port capacity check.

Written against cmk.graphing.v1, the API that replaces the legacy metrics/
and perfometer/ GUI extensions removed in 2.4.0.
"""

from cmk.graphing.v1 import Title
from cmk.graphing.v1.graphs import Graph
from cmk.graphing.v1.metrics import (
    Color,
    DecimalNotation,
    Metric,
    StrictPrecision,
    Unit,
)
from cmk.graphing.v1.perfometers import Closed, FocusRange, Perfometer

_UNIT_PORTS = Unit(DecimalNotation(""), StrictPrecision(0))
_UNIT_PERCENT = Unit(DecimalNotation("%"), StrictPrecision(1))

metric_iosxe_ports_total = Metric(
    name="iosxe_ports_total",
    title=Title("Ports in pool"),
    unit=_UNIT_PORTS,
    color=Color.GRAY,
)

metric_iosxe_ports_in_use = Metric(
    name="iosxe_ports_in_use",
    title=Title("Ports in use"),
    unit=_UNIT_PORTS,
    color=Color.BLUE,
)

metric_iosxe_ports_free = Metric(
    name="iosxe_ports_free",
    title=Title("Ports free"),
    unit=_UNIT_PORTS,
    color=Color.GREEN,
)

metric_iosxe_port_utilization = Metric(
    name="iosxe_port_utilization",
    title=Title("Capacity used"),
    unit=_UNIT_PERCENT,
    color=Color.ORANGE,
)

# Stacked in-use + free always sums to the pool size, so the graph shows both
# the trend and the ceiling without the total needing its own line.
graph_iosxe_port_capacity = Graph(
    name="iosxe_port_capacity",
    title=Title("Physical port capacity"),
    compound_lines=["iosxe_ports_in_use", "iosxe_ports_free"],
    simple_lines=["iosxe_ports_total"],
)

perfometer_iosxe_port_utilization = Perfometer(
    name="iosxe_port_utilization",
    focus_range=FocusRange(Closed(0), Closed(100)),
    segments=["iosxe_port_utilization"],
)
