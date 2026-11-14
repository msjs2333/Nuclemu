"""Package the selected measurement products from a single physical instant."""

from io import BytesIO
from zipfile import ZipFile

from .download_names import calibration_label, download_prefix, measurement_label


def make_download(lab, products):
    if not isinstance(products, list) or not products:
        raise ValueError("请选择要导出的测量产品。")
    prefix = download_prefix(lab.info)

    def file_for(item):
        content = lab.export(item)
        indices = item.get("indices", ())
        if item.get("kind") == "calibration":
            label = "calibration"
        elif len(indices) == 1:
            label = f"segment-{indices[0] + 1}"
        else:
            label = "segments"
        label = (calibration_label(lab.info, item['device']) if item.get("kind") == "calibration"
                 else f"{measurement_label(lab.info, item['device'])}-{label}")
        return f"{prefix}_{label}.{item['format']}", content

    if len(products) == 1:
        name, data = file_for(products[0])
        mime = "text/csv" if name.endswith(".csv") else "application/json"
        return name, mime + "; charset=utf-8", data

    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for position, item in enumerate(products, 1):
            name, data = file_for(item)
            archive.writestr(f"{prefix}_{position:03d}_{name[len(prefix)+1:]}", data)
    return f"{prefix}_records.zip", "application/zip", output.getvalue()
