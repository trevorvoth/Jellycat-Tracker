// Jellycat Tracker: collection view, add/edit/delete, and the family view with gift claims (Milestones 2-4).
// All user text goes into the page via textContent, never innerHTML, since anyone with the link can edit.
// Her view (no family token) never calls the claim functions: every claim request is behind state.familyToken.

const db = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

const COLUMNS = "id, name, nickname, size, category, status, notes, photo_path, acquired_date, acquired_from, created_at";
const PHOTO_MAX_SIDE = 1200;
const PHOTO_QUALITY = 0.8;
const UNDO_SECONDS = 6;
const STORE = { token: "jellycat.familyToken", name: "jellycat.claimName" };

const state = {
  items: [],
  tab: "owned",     // "owned" | "wishlist"
  query: "",
  category: "",
  loaded: false,
  detail: null,     // item shown in the detail view
  familyToken: null,
  claims: new Map(), // jellycat id -> claimed_by (family view only)
  claimName: null,
  busy: new Set(),  // item ids with a claim/got-it request in flight
};

// The add/edit form's own state.
const form = {
  editing: null,    // item being edited, or null when adding
  photoBlob: null,  // shrunk new photo waiting to be uploaded
  removePhoto: false,
  processing: false,
  saving: false,
};

const el = {
  title: document.getElementById("app-title"),
  tabs: document.querySelectorAll(".tab"),
  search: document.getElementById("search"),
  category: document.getElementById("category"),
  sectionTitle: document.getElementById("section-title"),
  count: document.getElementById("count"),
  status: document.getElementById("status"),
  grid: document.getElementById("grid"),
  addBtn: document.getElementById("add-btn"),

  formDialog: document.getElementById("form-dialog"),
  form: document.getElementById("item-form"),
  formTitle: document.getElementById("form-title"),
  nameError: document.getElementById("name-error"),
  photoInput: document.getElementById("photo-input"),
  photoLabel: document.getElementById("photo-label"),
  photoPreview: document.getElementById("photo-preview"),
  photoRemove: document.getElementById("photo-remove"),
  photoError: document.getElementById("photo-error"),
  categoryList: document.getElementById("category-list"),
  acquiredFields: document.getElementById("acquired-fields"),
  formError: document.getElementById("form-error"),
  saveBtn: document.getElementById("save-btn"),

  detailDialog: document.getElementById("detail-dialog"),
  detailName: document.getElementById("detail-name"),
  detailPhoto: document.getElementById("detail-photo"),
  detailFields: document.getElementById("detail-fields"),
  detailActions: document.getElementById("detail-actions"),

  familyBanner: document.getElementById("family-banner"),
  leaveFamily: document.getElementById("leave-family"),
  claimAs: document.getElementById("claim-as"),
  claimAsName: document.getElementById("claim-as-name"),
  changeName: document.getElementById("change-name"),
  nameDialog: document.getElementById("name-dialog"),
  nameForm: document.getElementById("name-form"),
  nameOk: document.getElementById("name-ok"),
  nameCancel: document.getElementById("name-cancel"),
  editBtn: document.getElementById("edit-btn"),
  deleteBtn: document.getElementById("delete-btn"),

  toast: document.getElementById("toast"),
  toastText: document.getElementById("toast-text"),
  toastUndo: document.getElementById("toast-undo"),
};

const SECTION_TITLES = { owned: "My Collection", wishlist: "Wishlist" };

const PLACEHOLDER_SVG =
  '<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' +
  '<ellipse cx="22" cy="14" rx="5" ry="11"/><ellipse cx="42" cy="14" rx="5" ry="11"/>' +
  '<circle cx="32" cy="38" r="17"/><circle cx="26" cy="35" r="1.5" fill="currentColor"/>' +
  '<circle cx="38" cy="35" r="1.5" fill="currentColor"/><path d="M29 42q3 3 6 0"/></svg>';

// ───── Data ─────

async function loadItems() {
  showStatus("loading");
  const [{ data, error }, claimsOk] = await Promise.all([
    db.from("jellycats").select(COLUMNS).is("deleted_at", null).order("created_at", { ascending: false }),
    state.familyToken ? loadClaims() : true,
  ]);

  if (error || !claimsOk) {
    if (error) console.error(error);
    showStatus("error");
    return;
  }
  state.items = data;
  state.loaded = true;
  fillCategories();
  render();
}

function photoUrl(path) {
  return db.storage.from("photos").getPublicUrl(path).data.publicUrl;
}

function putItem(item) {
  state.items = [item, ...state.items.filter((i) => i.id !== item.id)]
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  fillCategories();
}

function dropItem(id) {
  state.items = state.items.filter((i) => i.id !== id);
  fillCategories();
}

// ───── Filtering ─────

function visibleItems() {
  const q = state.query.trim().toLowerCase();
  return state.items.filter((item) => {
    if (item.status !== state.tab) return false;
    if (state.category && item.category !== state.category) return false;
    if (!q) return true;
    return [item.name, item.nickname, item.notes].some((f) => f && f.toLowerCase().includes(q));
  });
}

function allCategories() {
  return [...new Set(state.items.map((i) => i.category).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function fillCategories() {
  const categories = allCategories();
  if (state.category && !categories.includes(state.category)) state.category = "";

  el.category.replaceChildren(new Option("All categories", ""));
  for (const c of categories) el.category.add(new Option(c, c));
  el.category.value = state.category;
}

// ───── Rendering ─────

function render() {
  el.sectionTitle.textContent = SECTION_TITLES[state.tab];
  const items = visibleItems();
  el.count.textContent = `${items.length} ${items.length === 1 ? "Jellycat" : "Jellycats"}`;
  el.grid.replaceChildren(...items.map(card));

  if (items.length) {
    hideStatus();
  } else if (state.query.trim() || state.category) {
    showStatus("no-match");
  } else {
    showStatus("empty");
  }
}

function card(item) {
  const li = document.createElement("li");
  li.className = "card";
  li.dataset.id = item.id;

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "card-btn";
  btn.addEventListener("click", () => openDetail(item));

  const photo = photoTile(item, "card-photo");
  if (item.status === "wishlist") {
    const claimed = state.familyToken && state.claims.has(item.id);
    const badge = document.createElement("span");
    badge.className = claimed ? "badge badge-claimed" : "badge";
    badge.textContent = claimed ? "🎁 Claimed" : "Wishlist";
    photo.append(badge);
  }

  const name = document.createElement("h3");
  name.className = "card-name";
  name.textContent = item.name;
  btn.append(photo, name);

  const meta = [item.size, item.nickname && `“${item.nickname}”`].filter(Boolean).join(" · ");
  if (meta) {
    const p = document.createElement("p");
    p.className = "card-meta";
    p.textContent = meta;
    btn.append(p);
  }
  li.append(btn);

  // Wishlist cards: family sees claim status; her view gets a quick "Got it!".
  if (item.status === "wishlist") {
    const actions = document.createElement("div");
    actions.className = "card-actions";
    actions.append(...(state.familyToken ? claimControls(item) : [gotItButton(item)]));
    li.append(actions);
  }
  return li;
}

function claimControls(item) {
  const claimedBy = state.claims.get(item.id);
  if (claimedBy === undefined) {
    return [actionButton("Claim this", "btn btn-small", item, () => claim(item))];
  }
  const p = document.createElement("p");
  p.className = "claimed-by";
  const who = document.createElement("strong");
  who.textContent = claimedBy;
  p.append("🎁 Claimed by ", who);
  if (!isMine(claimedBy)) return [p];
  const undo = actionButton("Unclaim", "btn-link", item, () => unclaim(item));
  p.append(" · ", undo);
  return [p];
}

function gotItButton(item) {
  return actionButton("Got it! 🎉", "btn btn-small btn-success", item, () => gotIt(item));
}

function actionButton(label, className, item, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = className;
  btn.textContent = label;
  btn.disabled = state.busy.has(item.id);
  btn.addEventListener("click", onClick);
  return btn;
}

function photoTile(item, className) {
  const div = document.createElement("div");
  div.className = className;
  if (item.photo_path) {
    const img = document.createElement("img");
    img.src = photoUrl(item.photo_path);
    img.alt = item.name;
    img.loading = "lazy";
    img.addEventListener("error", () => img.replaceWith(placeholder()));
    div.append(img);
  } else {
    div.append(placeholder());
  }
  return div;
}

function placeholder() {
  const div = document.createElement("div");
  div.className = "placeholder";
  div.innerHTML = PLACEHOLDER_SVG + "<span>No photo yet</span>"; // static markup only
  return div;
}

function showStatus(kind) {
  const box = el.status;
  box.hidden = false;
  box.className = "status";
  box.replaceChildren();

  if (kind === "loading") {
    el.grid.replaceChildren();
    el.count.textContent = "";
    const spinner = document.createElement("div");
    spinner.className = "spinner";
    box.append(spinner, text("Gathering your Jellycats…"));
  } else if (kind === "error") {
    el.grid.replaceChildren();
    el.count.textContent = "";
    box.classList.add("is-error");
    const retry = document.createElement("button");
    retry.className = "btn";
    retry.textContent = "Retry";
    retry.addEventListener("click", loadItems);
    box.append(text("Couldn't load your Jellycats. Check your connection and try again."), retry);
  } else if (kind === "empty") {
    box.append(text(state.tab === "owned"
      ? "Your Jellycat family is waiting to grow… add your first!"
      : "The wishlist is empty… for now."));
  } else if (kind === "no-match") {
    const clear = document.createElement("button");
    clear.className = "btn btn-outline";
    clear.textContent = "Clear search";
    clear.addEventListener("click", clearFilters);
    box.append(text("No Jellycats match that search."), clear);
  }
}

function hideStatus() {
  el.status.hidden = true;
  el.status.replaceChildren();
}

function text(s) {
  const p = document.createElement("p");
  p.textContent = s;
  return p;
}

// ───── Detail view ─────

function openDetail(item) {
  state.detail = item;
  el.detailName.textContent = item.name;
  el.detailPhoto.replaceChildren(...photoTile(item, "detail-photo").childNodes);
  el.detailActions.replaceChildren(...(item.status === "wishlist"
    ? [...(state.familyToken ? claimControls(item) : []), gotItButton(item)]
    : []));

  const rows = [
    ["Nickname", item.nickname],
    ["Size", item.size],
    ["Category", item.category],
    ["Status", item.status === "owned" ? "In my collection" : "On my wishlist"],
    ["Date acquired", item.status === "owned" && formatDate(item.acquired_date)],
    ["From", item.status === "owned" && item.acquired_from],
    ["Notes", item.notes],
  ];
  el.detailFields.replaceChildren(...rows.filter(([, v]) => v).map(([label, value]) => {
    const row = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    row.append(dt, dd);
    return row;
  }));

  if (!el.detailDialog.open) el.detailDialog.showModal();
}

function formatDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

// ───── Add / edit form ─────

function openForm(item = null) {
  form.editing = item;
  form.photoBlob = null;
  form.removePhoto = false;
  form.processing = false;

  const f = el.form.elements;
  el.form.reset();
  el.formTitle.textContent = item ? "Edit Jellycat" : "Add a Jellycat";
  f.name.value = item?.name ?? "";
  f.nickname.value = item?.nickname ?? "";
  f.size.value = item?.size ?? "";
  f.category.value = item?.category ?? "";
  f.status.value = item?.status ?? state.tab;
  f.acquired_date.value = item ? (item.acquired_date ?? "") : today();
  f.acquired_from.value = item?.acquired_from ?? "";
  f.notes.value = item?.notes ?? "";

  el.categoryList.replaceChildren(...allCategories().map((c) => new Option(c)));
  setNameError(false);
  showPhotoError("");
  el.formError.hidden = true;
  updateAcquiredFields();
  showPreview(item?.photo_path ? photoUrl(item.photo_path) : null);
  setSaving(false);

  el.detailDialog.close();
  el.formDialog.showModal();
  if (!item) f.name.focus();
}

function today() {
  return new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD in local time
}

function updateAcquiredFields() {
  el.acquiredFields.hidden = el.form.elements.status.value !== "owned";
}

function showPreview(src) {
  el.photoPreview.classList.remove("is-busy");
  if (src) {
    const img = document.createElement("img");
    img.src = src;
    img.alt = "Photo preview";
    el.photoPreview.replaceChildren(img);
  } else {
    el.photoPreview.replaceChildren(placeholder());
  }
  el.photoRemove.hidden = !src;
  el.photoLabel.textContent = src ? "Change photo" : "Add photo";
}

function showPhotoError(message) {
  el.photoError.textContent = message;
  el.photoError.hidden = !message;
}

function setNameError(on) {
  el.nameError.hidden = !on;
  el.form.elements.name.closest(".field").classList.toggle("has-error", on);
}

function setSaving(on) {
  el.saveBtn.disabled = on || form.processing;
  el.saveBtn.textContent = on ? "Saving…" : form.processing ? "Preparing photo…" : "Save";
}

async function onPhotoChosen() {
  const file = el.photoInput.files[0];
  el.photoInput.value = ""; // so choosing the same file again still fires "change"
  if (!file) return;

  showPhotoError("");
  form.processing = true;
  setSaving(false);
  el.photoPreview.classList.add("is-busy");
  try {
    form.photoBlob = await shrinkPhoto(file);
    form.removePhoto = false;
    showPreview(URL.createObjectURL(form.photoBlob));
  } catch (err) {
    console.error(err);
    el.photoPreview.classList.remove("is-busy");
    showPhotoError("Couldn't read that photo. Try a different one.");
  } finally {
    form.processing = false;
    setSaving(form.saving);
  }
}

// Shrink to at most 1200px on the longest side and re-encode as JPEG, respecting the camera's rotation.
async function shrinkPhoto(file) {
  const source = await decodeImage(file);
  const scale = Math.min(1, PHOTO_MAX_SIDE / Math.max(source.width, source.height));
  const w = Math.round(source.width * scale);
  const h = Math.round(source.height * scale);

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#f7f7f7"; // matches the photo tile, for images with transparency
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(source, 0, 0, w, h);
  source.close?.();

  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("JPEG encode failed"))), "image/jpeg", PHOTO_QUALITY));
}

async function decodeImage(file) {
  try {
    return await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    // Older Safari: an <img> applies the camera rotation itself.
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      return img;
    } finally {
      URL.revokeObjectURL(url);
    }
  }
}

function removePhoto() {
  form.photoBlob = null;
  form.removePhoto = true;
  showPreview(null);
}

async function saveItem(event) {
  event.preventDefault();
  if (form.saving || form.processing) return; // ignore double taps

  const f = el.form.elements;
  const name = f.name.value.trim();
  if (!name) {
    setNameError(true);
    f.name.focus();
    return;
  }
  setNameError(false);
  el.formError.hidden = true;
  form.saving = true;
  setSaving(true);

  try {
    let photo_path = form.editing?.photo_path ?? null;
    if (form.photoBlob) {
      const path = `${uuid()}.jpg`;
      const { error } = await db.storage.from("photos").upload(path, form.photoBlob, { contentType: "image/jpeg" });
      if (error) throw error;
      photo_path = path;
    } else if (form.removePhoto) {
      photo_path = null;
    }

    const owned = f.status.value === "owned";
    const row = {
      name,
      nickname: blankToNull(f.nickname.value),
      size: blankToNull(f.size.value),
      category: blankToNull(f.category.value),
      status: f.status.value,
      acquired_date: owned ? blankToNull(f.acquired_date.value) : null,
      acquired_from: owned ? blankToNull(f.acquired_from.value) : null,
      notes: blankToNull(f.notes.value),
      photo_path,
    };

    const query = form.editing
      ? db.from("jellycats").update(row).eq("id", form.editing.id)
      : db.from("jellycats").insert(row);
    const { data, error } = await query.select(COLUMNS).single();
    if (error) throw error;

    const wasEditing = Boolean(form.editing);
    putItem(data);
    el.formDialog.close();
    if (data.status !== state.tab) setTab(data.status);
    else render();
    if (wasEditing) openDetail(data);
  } catch (err) {
    console.error(err);
    el.formError.textContent = "Couldn't save. Check your connection and try again.";
    el.formError.hidden = false;
  } finally {
    form.saving = false;
    setSaving(false);
  }
}

function blankToNull(value) {
  const v = value.trim();
  return v === "" ? null : v;
}

// crypto.randomUUID only exists on https pages; this also works on the local http test server.
function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// ───── Delete with undo ─────

let toastTimer = null;
let toastUndo = null;

async function deleteItem(item) {
  el.deleteBtn.disabled = true;
  const { error } = await db.from("jellycats").update({ deleted_at: new Date().toISOString() }).eq("id", item.id);
  el.deleteBtn.disabled = false;
  if (error) {
    console.error(error);
    showToast("Couldn't delete. Try again.");
    return;
  }
  el.detailDialog.close();
  dropItem(item.id);
  render();
  showToast(`${item.name} deleted`, async () => {
    const { error } = await db.from("jellycats").update({ deleted_at: null }).eq("id", item.id);
    if (error) {
      console.error(error);
      showToast("Couldn't undo. Try again.");
      return;
    }
    putItem(item);
    render();
  });
}

function showToast(message, onUndo = null) {
  clearTimeout(toastTimer);
  toastUndo = onUndo;
  el.toastText.textContent = message;
  el.toastUndo.hidden = !onUndo;
  el.toast.hidden = false;
  toastTimer = setTimeout(hideToast, UNDO_SECONDS * 1000);
}

function hideToast() {
  clearTimeout(toastTimer);
  el.toast.hidden = true;
  toastUndo = null;
}

// ───── Family view and gift claims ─────

function readStore(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function writeStore(key, value) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* private mode etc.: family view just won't be remembered */ }
}

// A family link looks like .../?f=<token>. The token is checked, remembered, and removed from the address bar.
async function initFamily() {
  const params = new URLSearchParams(location.search);
  const fromLink = params.get("f");
  if (fromLink !== null) {
    const { data, error } = await db.rpc("check_family_token", { p_token: fromLink });
    if (error) {
      console.error(error); // network trouble: keep the link in the address bar so a reload can retry
    } else {
      if (data === true) writeStore(STORE.token, fromLink);
      // A wrong token quietly falls back to her view and saves nothing.
      params.delete("f");
      const rest = params.toString();
      history.replaceState(null, "", location.pathname + (rest ? `?${rest}` : "") + location.hash);
    }
  }
  state.familyToken = readStore(STORE.token);
  state.claimName = readStore(STORE.name);
  updateFamilyBanner();
}

async function loadClaims() {
  const { data, error } = await db.rpc("get_claims", { p_token: state.familyToken });
  if (error) {
    console.error(error);
    if (error.code === "28000") { // token no longer valid (rotated): back to her view
      leaveFamily();
      showToast("This family link has expired. Ask for the new one.");
      return true;
    }
    return false;
  }
  state.claims = new Map(data.map((c) => [c.jellycat_id, c.claimed_by]));
  return true;
}

function leaveFamily() {
  writeStore(STORE.token, null);
  state.familyToken = null;
  state.claims = new Map();
  updateFamilyBanner();
  refresh();
}

function updateFamilyBanner() {
  el.familyBanner.hidden = !state.familyToken;
  el.claimAs.hidden = !state.claimName;
  el.claimAsName.textContent = state.claimName ?? "";
}

function isMine(claimedBy) {
  return Boolean(state.claimName) && claimedBy.trim().toLowerCase() === state.claimName.trim().toLowerCase();
}

// Re-draw the grid and, if open, the detail view (with the item's latest data).
function refresh() {
  if (!state.loaded) return;
  render();
  if (el.detailDialog.open && state.detail) {
    const latest = state.items.find((i) => i.id === state.detail.id);
    if (latest) openDetail(latest);
    else el.detailDialog.close();
  }
}

function askName(buttonLabel = "Claim it") {
  return new Promise((resolve) => {
    const input = el.nameForm.elements.claimer;
    input.value = state.claimName ?? "";
    el.nameOk.textContent = buttonLabel;
    const done = (name) => {
      el.nameForm.removeEventListener("submit", onSubmit);
      el.nameCancel.removeEventListener("click", onCancel);
      el.nameDialog.removeEventListener("cancel", onCancel);
      el.nameDialog.close();
      resolve(name);
    };
    const onSubmit = (e) => {
      e.preventDefault();
      const name = input.value.trim();
      if (!name) { input.focus(); return; }
      state.claimName = name;
      writeStore(STORE.name, name);
      updateFamilyBanner();
      done(name);
    };
    const onCancel = (e) => { e.preventDefault(); done(null); };
    el.nameForm.addEventListener("submit", onSubmit);
    el.nameCancel.addEventListener("click", onCancel);
    el.nameDialog.addEventListener("cancel", onCancel);
    el.nameDialog.showModal();
    input.focus();
  });
}

// Runs one claim/got-it request per item at a time, with its buttons disabled meanwhile.
async function withBusy(item, fn) {
  if (state.busy.has(item.id)) return;
  state.busy.add(item.id);
  refresh();
  try {
    await fn();
  } finally {
    state.busy.delete(item.id);
    refresh();
  }
}

function claim(item) {
  return withBusy(item, async () => {
    const name = state.claimName || await askName();
    if (!name) return;
    const { error } = await db.rpc("claim_item", { p_token: state.familyToken, p_jellycat_id: item.id, p_name: name });
    if (!error) {
      state.claims.set(item.id, name);
      showToast(`Claimed! ${OWNER_NAME} can't see this.`);
      return;
    }
    console.error(error);
    if (error.code === "23505") { // someone else got there first
      await loadClaims();
      showToast(`Already claimed by ${state.claims.get(item.id) ?? "someone else"}.`);
    } else if (error.code === "P0002") { // no longer on the wishlist
      showToast("That's not on the wishlist any more.");
      await loadItems();
    } else if (error.code === "28000") {
      leaveFamily();
      showToast("This family link has expired. Ask for the new one.");
    } else {
      showToast("Couldn't claim. Try again.");
    }
  });
}

function unclaim(item) {
  return withBusy(item, async () => {
    const { error } = await db.rpc("unclaim_item", { p_token: state.familyToken, p_jellycat_id: item.id });
    if (error) {
      console.error(error);
      showToast("Couldn't unclaim. Try again.");
      return;
    }
    state.claims.delete(item.id);
    showToast("Unclaimed. Someone else can pick it now.");
  });
}

// "Got it!": move to the collection. The database clears any gift claim on its own,
// recording the claimer as "Gift from <name>" in acquired_from.
function gotIt(item) {
  return withBusy(item, async () => {
    const before = { status: item.status, acquired_date: item.acquired_date, acquired_from: item.acquired_from };
    const { data, error } = await db.from("jellycats")
      .update({ status: "owned", acquired_date: item.acquired_date ?? today() })
      .eq("id", item.id).select(COLUMNS).single();
    if (error) {
      console.error(error);
      showToast("Couldn't update. Try again.");
      return;
    }
    state.claims.delete(item.id);
    putItem(data);
    el.detailDialog.close();
    showToast(`${item.name} joined the collection! 🎉`, async () => {
      const { data: back, error } = await db.from("jellycats").update(before).eq("id", item.id).select(COLUMNS).single();
      if (error) {
        console.error(error);
        showToast("Couldn't undo. Try again.");
        return;
      }
      putItem(back);
      refresh();
    });
  });
}

// ───── Events ─────

function setTab(tab) {
  state.tab = tab;
  for (const t of el.tabs) {
    const active = t.dataset.tab === tab;
    t.classList.toggle("is-active", active);
    t.setAttribute("aria-selected", String(active));
  }
  if (state.loaded) render();
}

function clearFilters() {
  state.query = "";
  state.category = "";
  el.search.value = "";
  el.category.value = "";
  render();
}

for (const t of el.tabs) t.addEventListener("click", () => setTab(t.dataset.tab));

el.search.addEventListener("input", () => {
  state.query = el.search.value;
  if (state.loaded) render();
});

el.category.addEventListener("change", () => {
  state.category = el.category.value;
  if (state.loaded) render();
});

el.addBtn.addEventListener("click", () => openForm());
el.form.addEventListener("submit", saveItem);
el.form.elements.name.addEventListener("input", () => setNameError(false));
for (const r of el.form.elements.status) r.addEventListener("change", updateAcquiredFields);
el.photoInput.addEventListener("change", onPhotoChosen);
el.photoRemove.addEventListener("click", removePhoto);

el.editBtn.addEventListener("click", () => openForm(state.detail));
el.deleteBtn.addEventListener("click", () => deleteItem(state.detail));

el.toastUndo.addEventListener("click", () => {
  const undo = toastUndo;
  hideToast();
  undo?.();
});

for (const dialog of [el.formDialog, el.detailDialog]) {
  for (const btn of dialog.querySelectorAll("[data-close]")) btn.addEventListener("click", () => dialog.close());
}
// Tapping the dimmed backdrop closes the detail view (not the form, so typing isn't lost by accident).
el.detailDialog.addEventListener("click", (e) => {
  if (e.target === el.detailDialog) el.detailDialog.close();
});

el.leaveFamily.addEventListener("click", () => {
  leaveFamily();
  showToast("You've left family view.");
});
el.changeName.addEventListener("click", () => askName("Save"));

document.title = APP_TITLE;
el.title.textContent = APP_TITLE;
for (const span of document.querySelectorAll("#owner-name, .owner-name")) span.textContent = OWNER_NAME;
showStatus("loading");
initFamily().then(loadItems);
