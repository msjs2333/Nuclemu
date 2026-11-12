"""Thin Web adapter for explicit cached measurements in portable exchanges."""

from copy import deepcopy

from .exchange import (batch_download, capture_session, load_package,
                       package_download, reopen_session, validate_document)


class WebExchange:
    """Keep portable item identities stable across captures and downloads.

    ``refresh`` accepts the Web workbench product and per-device analysis. A
    legacy segment index is bound only if exactly one saved snapshot represents
    the entire segment, including its bounds, acquisition, settings and counts.
    Unmatched or ambiguous selections remain null and their indices are kept
    in ``unresolved`` for the caller to show to the user.
    """

    def __init__(self, previous_document=None):
        self.document = deepcopy(validate_document(previous_document)) if previous_document is not None else None

    def refresh(self, session, *, device=None, definition=None, product=None, analysis=None, item_indices=None,
                preserved_analysis=None, identity_analysis=None):
        # First collect snapshots; no preview or live observation is created.
        doc = capture_session(session, self.document, definition=definition, device=device)
        if analysis is not None:
            translated = {}
            segments = product.get("segments", []) if product is not None else []
            for instrument, values in analysis.items():
                selection = deepcopy(values)
                unresolved = {}
                for key in ("selected", "reference", "background"):
                    explicit = (identity_analysis or {}).get(instrument, {}).get(key)
                    if explicit is not None:
                        selection[key] = explicit
                        continue
                    preserved = (preserved_analysis or {}).get(instrument, {}).get(key)
                    if preserved is not None:
                        selection[key] = preserved
                        unresolved[key] = preserved
                        continue
                    index = values.get(key)
                    if index is None:
                        selection[key] = None
                        continue
                    matches = []
                    if item_indices:
                        matches = [identity for identity, indices in item_indices.items() if tuple(indices) == (index,)
                                   and any(item['id'] == identity and instrument in item['document'].get('devices', {}) for item in doc['items'])]
                    if not matches and type(index) is int and 0 <= index < len(segments):
                        segment = segments[index]
                        if instrument in segment.get("readings", {}):
                            expected = dict(segment, readings={instrument: segment["readings"][instrument]})
                            for item in doc["items"]:
                                data = item["document"]
                                snap = data.get("snapshot", {})
                                if (item["kind"] == "measurement" and snap.get("device") == instrument
                                        and data.get("segments") == [expected]):
                                    matches.append(item["id"])
                    selection[key] = matches[0] if len(matches) == 1 else None
                    if len(matches) != 1:
                        unresolved[key] = index
                if unresolved:
                    selection["unresolved"] = unresolved
                else:
                    selection.pop("unresolved", None)
                translated[instrument] = selection
            doc["analysis"] = translated
            validate_document(doc)
        self.document = doc
        return deepcopy(doc)

    def download_package(self):
        """Return the full experiment; checkbox selections never filter it."""
        return package_download(self._document())

    def download_selected(self, selections):
        """Download [{id: item UUID or native snapshot id, format: ...}]."""
        doc = self._document()
        mapped = []
        for choice in selections:
            identity = choice["id"]
            if type(identity) is int:
                matches = [item["id"] for item in doc["items"]
                           if item["kind"] == "measurement"
                           and item["source"]["package"] == doc["id"]
                           and item["source"]["item"] == item["id"]
                           and item["document"].get("snapshot", {}).get("id") == identity]
                if len(matches) != 1:
                    raise ValueError("Unknown or ambiguous cached snapshot")
                identity = matches[0]
            mapped.append({"id": identity, "format": choice["format"]})
        return batch_download(doc, mapped)

    def _document(self):
        if self.document is None:
            raise ValueError("Capture or load an experiment before downloading")
        return self.document

    @classmethod
    def load(cls, source, experiment, *, seed=None):
        """Decode a portable package and reopen an idle session without sampling."""
        doc = load_package(source)
        session = reopen_session(doc, experiment, seed=seed)
        return cls(doc), session
