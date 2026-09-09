import { UserManager, WebStorageStateStore, type User } from "oidc-client-ts";
import "./styles.css";

type CaseStatus =
  | "received"
  | "gathering_facts"
  | "ready_for_policy"
  | "awaiting_decision"
  | "authorized"
  | "executing"
  | "verifying"
  | "reconciling"
  | "reopen_required"
  | "waiting"
  | "completed"
  | "cancelled"
  | "failed";

type QueueItem = {
  case_id: string;
  case_kind: string;
  status: CaseStatus;
  subject_ref: string;
  requester_principal_id: string;
  version: number;
  authority_epoch: number;
  updated_at: string;
};

type CaseDetail = {
  case: Record<string, unknown>;
  policy: Record<string, unknown> | null;
  governance: Record<string, unknown> | null;
  obligations: Record<string, unknown> | null;
  effects: Array<Record<string, unknown>>;
  outcomes: Array<Record<string, unknown>>;
  audit: Array<Record<string, unknown>> | null;
};

const config = {
  apiBase: import.meta.env.VITE_OPERATIONS_API_BASE_URL || "http://127.0.0.1:8001",
  oidcAuthority: import.meta.env.VITE_OIDC_AUTHORITY || "",
  oidcClientId: import.meta.env.VITE_OIDC_CLIENT_ID || "",
  oidcScope: import.meta.env.VITE_OIDC_SCOPE || "openid profile email",
};

const root = document.querySelector<HTMLDivElement>("#app")!;
if (!root) throw new Error("#app is required");

const userManager =
  config.oidcAuthority && config.oidcClientId
    ? new UserManager({
        authority: config.oidcAuthority,
        client_id: config.oidcClientId,
        redirect_uri: `${window.location.origin}${window.location.pathname}`,
        post_logout_redirect_uri: `${window.location.origin}${window.location.pathname}`,
        response_type: "code",
        scope: config.oidcScope,
        userStore: new WebStorageStateStore({ store: window.sessionStorage }),
        stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
        automaticSilentRenew: false,
      })
    : null;

let currentUser: User | null = null;
let queue: QueueItem[] = [];
let selected: CaseDetail | null = null;
let selectedId: string | null = null;
let errorMessage = "";
let busy = false;

async function init(): Promise<void> {
  if (userManager && window.location.search.includes("code=")) {
    currentUser = await userManager.signinRedirectCallback();
    window.history.replaceState({}, document.title, window.location.pathname);
  } else if (userManager) {
    currentUser = await userManager.getUser();
  }
  render();
  if (currentUser && !currentUser.expired) {
    await loadQueue();
  }
}

function token(): string {
  if (!currentUser || currentUser.expired || !currentUser.access_token) {
    throw new Error("OIDC session is not authenticated");
  }
  return currentUser.access_token;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token()}`);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${config.apiBase}${path}`, { ...init, headers });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}${text ? `: ${text}` : ""}`);
  }
  return (await response.json()) as T;
}

async function loadQueue(): Promise<void> {
  busy = true;
  errorMessage = "";
  render();
  try {
    queue = await api<QueueItem[]>(
      "/v1/operations/cases?status=reconciling&status=reopen_required&status=waiting&status=failed&limit=500",
    );
    if (selectedId && queue.some((item) => item.case_id === selectedId)) {
      selected = await api<CaseDetail>(`/v1/operations/cases/${selectedId}`);
    }
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function selectCase(caseId: string): Promise<void> {
  busy = true;
  errorMessage = "";
  selectedId = caseId;
  render();
  try {
    selected = await api<CaseDetail>(`/v1/operations/cases/${caseId}`);
  } catch (error) {
    selected = null;
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function refreshAuthoritativeFacts(): Promise<void> {
  if (!selectedId) return;
  if (!window.confirm("Refresh current authoritative HRIS facts and force policy/governance re-evaluation?")) {
    return;
  }
  busy = true;
  errorMessage = "";
  render();
  try {
    await api(`/v1/operations/cases/${selectedId}/authoritative-facts/refresh`, {
      method: "POST",
    });
    selected = await api<CaseDetail>(`/v1/operations/cases/${selectedId}`);
    await loadQueue();
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function login(): Promise<void> {
  if (!userManager) {
    errorMessage = "OIDC console configuration is missing.";
    render();
    return;
  }
  await userManager.signinRedirect();
}

async function logout(): Promise<void> {
  if (!userManager) return;
  await userManager.signoutRedirect();
}

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function pretty(value: unknown): string {
  return escapeHtml(JSON.stringify(value, null, 2));
}

function statusClass(status: CaseStatus): string {
  if (status === "failed" || status === "reopen_required") return "danger";
  if (status === "reconciling" || status === "waiting") return "warn";
  if (status === "completed") return "ok";
  return "neutral";
}

function render(): void {
  const authenticated = Boolean(currentUser && !currentUser.expired);
  root.innerHTML = `
    <header class="topbar">
      <div>
        <div class="eyebrow">Human Exception Operations Surface</div>
        <h1>Administrative Operations</h1>
      </div>
      <div class="session">
        ${authenticated ? `<span>${escapeHtml(currentUser?.profile.sub)}</span><button id="logout">Sign out</button>` : `<button id="login">Sign in</button>`}
      </div>
    </header>
    <main class="layout">
      <aside class="queue-panel">
        <div class="panel-heading">
          <div>
            <h2>Exception queue</h2>
            <p>WAIT / RECONCILE / REASSESS / HUMAN REVIEW only.</p>
          </div>
          <button id="refresh" ${authenticated && !busy ? "" : "disabled"}>Refresh</button>
        </div>
        ${
          authenticated
            ? `<div class="queue">${queue
                .map(
                  (item) => `
                    <button class="queue-item ${item.case_id === selectedId ? "selected" : ""}" data-case-id="${escapeHtml(item.case_id)}">
                      <div class="queue-row"><strong>${escapeHtml(item.subject_ref)}</strong><span class="badge ${statusClass(item.status)}">${escapeHtml(item.status)}</span></div>
                      <div class="muted">${escapeHtml(item.case_kind)} · epoch ${item.authority_epoch} · v${item.version}</div>
                      <div class="muted">${escapeHtml(new Date(item.updated_at).toLocaleString())}</div>
                    </button>`,
                )
                .join("") || `<div class="empty">No current exceptions.</div>`}</div>`
            : `<div class="empty">Authenticate through OIDC to inspect governed operations.</div>`
        }
      </aside>
      <section class="detail-panel">
        ${errorMessage ? `<div class="error">${escapeHtml(errorMessage)}</div>` : ""}
        ${busy ? `<div class="loading">Loading current authoritative state…</div>` : ""}
        ${selected ? renderDetail(selected) : `<div class="empty detail-empty">Select an exception case.</div>`}
      </section>
    </main>
    <footer>
      No force-complete, mark-success, evidence override, Kernel authorization, or provider retry controls exist in this console.
    </footer>
  `;

  root.querySelector<HTMLButtonElement>("#login")?.addEventListener("click", () => void login());
  root.querySelector<HTMLButtonElement>("#logout")?.addEventListener("click", () => void logout());
  root.querySelector<HTMLButtonElement>("#refresh")?.addEventListener("click", () => void loadQueue());
  root.querySelector<HTMLButtonElement>("#authoritative-refresh")?.addEventListener("click", () =>
    void refreshAuthoritativeFacts(),
  );
  root.querySelectorAll<HTMLButtonElement>("[data-case-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const caseId = button.dataset.caseId;
      if (caseId) void selectCase(caseId);
    });
  });
}

function renderDetail(detail: CaseDetail): string {
  const caseValue = detail.case;
  const status = String(caseValue.status ?? "unknown") as CaseStatus;
  return `
    <div class="detail-heading">
      <div>
        <div class="eyebrow">${escapeHtml(caseValue.case_kind)}</div>
        <h2>${escapeHtml(caseValue.subject_ref)}</h2>
        <div class="muted">case ${escapeHtml(caseValue.case_id)} · epoch ${escapeHtml(caseValue.authority_epoch)}</div>
      </div>
      <div class="actions">
        <span class="badge ${statusClass(status)}">${escapeHtml(status)}</span>
        <button id="authoritative-refresh" ${busy ? "disabled" : ""}>Refresh authoritative facts</button>
      </div>
    </div>
    <div class="cards">
      ${section("Current case", caseValue)}
      ${section("Policy", detail.policy)}
      ${section("Governance basis", detail.governance)}
      ${section("Obligations", detail.obligations)}
      ${section("Kernel-backed effects", detail.effects)}
      ${section("Confirmed outcomes", detail.outcomes)}
      ${detail.audit === null ? `<article class="card"><h3>Audit</h3><p class="muted">Not disclosed to this principal. Audit authority is separate from operations visibility.</p></article>` : section("Audit", detail.audit)}
    </div>
  `;
}

function section(title: string, value: unknown): string {
  return `<article class="card"><h3>${escapeHtml(title)}</h3><pre>${pretty(value)}</pre></article>`;
}

void init().catch((error) => {
  errorMessage = error instanceof Error ? error.message : String(error);
  render();
});
