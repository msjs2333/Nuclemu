"""In-memory inspection and explicit import of portable saved items for Web."""

from copy import deepcopy
from uuid import uuid4

from .exchange import FORMAT, import_item, list_items, load_item, load_package, validate_document
from .web_exchange import WebExchange
from .web_portable import SavedOverlay


def inspect_import(lab, raw):
    """Decode a package or saved-item bundle and replace this lab's pending choice."""
    if lab.readonly or not lab.work.session.experiment.outputs:
        raise ValueError("请在可继续采集的实验中导入保存项。")
    if not isinstance(raw, bytes):
        raise ValueError("Import requires file bytes")
    source = load_package(raw) if raw.startswith((b"PK\x03\x04", b"SQLite format 3\0")) else load_item(raw)
    if source["definition"]["id"] != lab.work.session.experiment.id:
        raise ValueError("保存项属于不同课程。")
    if source.get("legacy"):
        raise ValueError("历史包请先通过只读转存查看。")
    items = list_items(source) if source.get("format") == FORMAT else [
        dict(id=i["id"], title=i["title"], kind=i["kind"],
             device=i["document"].get("snapshot", {}).get("device", i["document"].get("device")),
             exposure_s=i["document"].get("snapshot", {}).get("exposure_s")) for i in source["items"]]
    token = uuid4().hex
    lab._pending_import = (token, source)
    return dict(token=token, items=items)


def apply_import(lab, token, item_id):
    """Copy one item with a new UUID and insert its segments before live history."""
    pending = getattr(lab, "_pending_import", None)
    if pending is None or not isinstance(token, str) or token != pending[0]:
        raise ValueError("导入选择已过期，请重新选择文件。")
    if lab.readonly or not lab.work.session.experiment.outputs:
        raise ValueError("请在可继续采集的实验中导入保存项。")
    work, source = lab.work, pending[1]
    view = work.lab.view
    product = work.product()
    # Keep the preexisting document untouched if validation of the import fails.
    exchange = WebExchange(lab.exchange.document)
    doc = exchange.refresh(work.session, device=work.device.id, definition=lab.info,
                               product=product, analysis=lab.analysis, item_indices=getattr(view, 'item_indices', None),
                               preserved_analysis=getattr(lab, 'portable_preserved_analysis', None), identity_analysis=lab.saved_analysis)
    validate_document(doc)
    new_id = import_item(doc, source, item_id)
    imported = next(i for i in doc["items"] if i["id"] == new_id)
    if not isinstance(view, SavedOverlay):
        view = SavedOverlay(work.session, [], live=view, package_id=doc['id'])
    old_prefix = len(view.prefix)
    added = view.append_items([imported])
    if added:
        for selection in lab.analysis.values():
            for key in ("selected", "reference", "background"):
                if selection.get(key) is not None and selection[key] >= old_prefix:
                    selection[key] += added
        defaults = getattr(lab, "portable_default_selection", {})
        for device, index in defaults.items():
            if index >= old_prefix:
                defaults[device] += added
        lab._saved_ends = {(i + added if i >= old_prefix else i, d): end
                           for (i, d), end in lab._saved_ends.items()}
        lab._pending = {(i + added if i >= old_prefix else i, d):
                        dict(value, index=i + added if i >= old_prefix else i)
                        for (i, d), value in lab._pending.items()}
        lab._pending_entries = list(lab._pending.values())
        lab._dirty_segments += added
        lab.draft_segments += added
        lab._counter_analysis_key = None
    work.lab.view = view
    indices = view.item_indices.get(new_id, ())
    reference = None
    work_device = work.device.id
    lab.bind(work_device, restore_calibration=False)
    lab.exchange.document = doc
    lab.product_generation = getattr(lab, "product_generation", 0) + 1
    del lab._pending_import
    return dict(id=new_id, kind=imported["kind"], reference=reference,
                segments=len(indices), multi_segment=len(indices) > 1)
