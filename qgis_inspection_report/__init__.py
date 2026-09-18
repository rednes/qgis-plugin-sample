"""Inspection Report プラグインのエントリポイント。"""


def classFactory(iface):
    from .main_plugin import InspectionReportPlugin

    return InspectionReportPlugin(iface)
