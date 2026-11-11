"""Package the selected measurement products from a single physical instant."""

from io import BytesIO
import re
from zipfile import ZipFile


def make_download(lab, products):
    if not isinstance(products, list) or not products:
        raise ValueError("请选择要导出的测量产品。")

    def file_for(item):
        content = lab.export(item)
        indices = item.get("indices", ())
        if item.get("kind") == "calibration":
            label = "calibration"
        elif len(indices) == 1:
            label = f"segment-{indices[0] + 1}"
        else:
            label = "segments"
        stem = re.sub(r"[^\w.-]+", "_", f"{lab.info['id']}-{item['device']}-{label}").strip(".")
        return f"{stem}.{item['format']}", content

    if len(products) == 1:
        name, data = file_for(products[0])
        mime = "text/csv" if name.endswith(".csv") else "application/json"
        return name, mime + "; charset=utf-8", data

    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for position, item in enumerate(products, 1):
            name, data = file_for(item)
            archive.writestr(f"{position}-{name}", data)
    return "nuclemu-products.zip", "application/zip", output.getvalue()
