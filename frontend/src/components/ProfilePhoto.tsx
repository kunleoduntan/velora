import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

const MAX_BYTES = 5 * 1024 * 1024;

/** The record's picture, shown at the top of its form. The image is an attachment of the record; the image field holds its id. */
export default function ProfilePhoto({ doctype, name, imageId, title, canWrite, onChange }: {
  doctype: string; name: string | null; imageId: string; title: string; canWrite: boolean; onChange: (id: string) => void;
}) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true; let made = "";
    setUrl("");
    if (imageId) {
      api.downloadAttachment(imageId).then(({ blob }) => { if (alive) { made = URL.createObjectURL(blob); setUrl(made); } }).catch(() => { /* shows initials */ });
    }
    return () => { alive = false; if (made) URL.revokeObjectURL(made); };
  }, [imageId]);

  async function pick(file?: File) {
    if (!file || !name) return;
    if (!file.type.startsWith("image/")) return setError("Choose an image file (PNG, JPG, WEBP).");
    if (file.size > MAX_BYTES) return setError("The picture must be smaller than 5 MB.");
    setBusy(true); setError("");
    try {
      const saved = await api.uploadAttachment(doctype, name, file, "Profile photo");
      onChange(String(saved.id));
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  const initials = title.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("") || "?";
  return (
    <div className="profile-photo">
      <div className="profile-photo-frame" aria-label="Profile photo">
        {url ? <img src={url} alt={`${title} photo`} /> : <span aria-hidden="true">{initials}</span>}
      </div>
      {canWrite && name && (
        <div className="profile-photo-actions">
          <label className="rbtn">
            <span>{imageId ? "Change photo" : "Upload photo"}</span>
            <input type="file" accept="image/*" aria-label="Choose photo" disabled={busy} hidden onChange={(e) => { const f = e.target.files?.[0]; void pick(f); e.currentTarget.value = ""; }} />
          </label>
          {imageId && <button type="button" className="rbtn" onClick={() => onChange("")}>Remove</button>}
        </div>
      )}
      {canWrite && !name && <small className="muted">Save first, then add a photo.</small>}
      {error && <div className="error" role="alert">{error}</div>}
    </div>
  );
}
