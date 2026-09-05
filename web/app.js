/* Poker Ledger - a small hash-routed page over the JSON API.
   No framework and no build step: the whole thing is this file. */

'use strict';

const view = document.getElementById('view');
const viewTitle = document.getElementById('view-title');
const viewAction = document.getElementById('view-action');
const modalRoot = document.getElementById('modal-root');
const toastEl = document.getElementById('toast');

/* ------------------------------------------------------------------ utils */

const SYMBOLS = { EUR: '€', USD: '$', GBP: '£' };
const SUIT_GLYPH = { s: '♠', h: '♥', d: '♦', c: '♣' };
const RANK_ORDER = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2'];
const SUIT_ORDER = ['s', 'h', 'd', 'c'];

/* Cards travel as "Th" because the API wants one character per rank, but a
   lone T does not read as a ten when you are scanning a grid of thirteen. */
function rankLabel(rank) {
  return rank === 'T' ? '10' : rank;
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function money(cents, currency = 'EUR') {
  const symbol = SYMBOLS[currency] || currency + ' ';
  const sign = cents < 0 ? '-' : '';
  const amount = (Math.abs(cents) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
  return `${sign}${symbol}${amount}`;
}

/* Signed from the player's side of the table: a buy-in is money they handed
   over, a cash-out is money they got back. Stored unsigned either way. */
function entrySign(txn) {
  return txn.kind === 'buy_in' ? -txn.amount_cents : txn.amount_cents;
}

function signed(cents, currency) {
  const cls = cents > 0 ? 'pos' : cents < 0 ? 'neg' : '';
  const prefix = cents > 0 ? '+' : '';
  return `<span class="money ${cls}">${prefix}${esc(money(cents, currency))}</span>`;
}

/** Accepts "50", "50.25", "€50" and returns whole cents, or null. */
function parseMoney(text) {
  const cleaned = String(text ?? '').replace(/[^0-9.,-]/g, '').replace(',', '.');
  if (!cleaned || cleaned === '-' || cleaned === '.') return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value)) return null;
  return Math.round(value * 100);
}

/* Blinds are spoken as one thing - "we play 10/20" - so they are typed as one
   thing rather than as two boxes. */
function parseBlinds(text) {
  const parts = String(text ?? '').split('/');
  const small = parseMoney(parts[0]) || 0;
  const big = parseMoney(parts[1]) || 0;
  return { small, big };
}

function blindsLabel(game) {
  if (!game.big_blind_cents) return '';
  const strip = (cents) => (cents % 100 === 0 ? cents / 100 : (cents / 100).toFixed(2));
  const symbol = SYMBOLS[game.currency] || '';
  return `${symbol}${strip(game.small_blind_cents)}/${strip(game.big_blind_cents)}`;
}

function shortDate(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

let toastTimer;

/** toast('Saved') · toast('Nope', { error: true }) */
function toast(message, options = {}) {
  const { error = false } = options;
  toastEl.textContent = message;
  toastEl.classList.toggle('error', error);
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.hidden = true; }, error ? 4200 : 2200);
}

async function api(path, options = {}) {
  const response = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === 'string' ? detail : 'Something went wrong');
  }
  return data;
}

/** Runs an API call, showing the server's message on failure. */
async function attempt(fn) {
  try {
    return await fn();
  } catch (error) {
    toast(error.message, { error: true });
    return undefined;
  }
}

/* ------------------------------------------------------------------ modal */

function showModal({ title, fields = [], submitLabel = 'Save', danger = false, message }) {
  return new Promise((resolve) => {
    modalRoot.innerHTML = `
      <form class="modal" id="modal-form">
        <h3>${esc(title)}</h3>
        ${message ? `<p class="muted" style="margin-top:-6px">${esc(message)}</p>` : ''}
        ${fields.map((field) => `
          <div class="field">
            ${field.label ? `<label for="f-${esc(field.name)}">${esc(field.label)}</label>` : ''}
            ${field.options
              ? `<select id="f-${esc(field.name)}" name="${esc(field.name)}">
                   ${field.options.map((o) =>
                     `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('')}
                 </select>`
              : `<input id="f-${esc(field.name)}" name="${esc(field.name)}"
                        type="${esc(field.type || 'text')}"
                        inputmode="${esc(field.inputmode || 'text')}"
                        value="${esc(field.value ?? '')}"
                        placeholder="${esc(field.placeholder || '')}"
                        autocomplete="off">`}
          </div>`).join('')}
        <div class="row" style="gap:10px;margin-top:6px">
          <button type="button" class="ghost grow" id="modal-cancel">Cancel</button>
          <button type="submit" class="grow ${danger ? 'danger' : 'primary'}">${esc(submitLabel)}</button>
        </div>
      </form>`;
    modalRoot.hidden = false;

    const form = document.getElementById('modal-form');
    const close = (result) => { modalRoot.hidden = true; modalRoot.innerHTML = ''; resolve(result); };

    document.getElementById('modal-cancel').onclick = () => close(null);
    modalRoot.onclick = (event) => { if (event.target === modalRoot) close(null); };
    form.onsubmit = (event) => {
      event.preventDefault();
      close(Object.fromEntries(new FormData(form).entries()));
    };

    const first = form.querySelector('input, select');
    if (first) setTimeout(() => first.focus(), 40);
  });
}

function confirmModal(title, message, submitLabel = 'Confirm') {
  return showModal({ title, message, submitLabel, danger: true }).then((r) => r !== null);
}

/* ------------------------------------------------------------------ router */

const routes = [
  [/^\/games$/, () => renderGames()],
  [/^\/game\/(\d+)$/, (id) => renderGame(Number(id))],
  [/^\/players$/, () => renderPlayers()],
  [/^\/odds$/, () => renderOdds()],
];

function currentPath() {
  return location.hash.replace(/^#/, '') || '/games';
}

async function route() {
  const path = currentPath();
  const tab = path.startsWith('/players') ? 'players' : path.startsWith('/odds') ? 'odds' : 'games';
  document.querySelectorAll('.tabbar a').forEach((a) => {
    a.classList.toggle('active', a.dataset.tab === tab);
  });
  viewAction.innerHTML = '';

  for (const [pattern, handler] of routes) {
    const match = path.match(pattern);
    if (match) {
      await handler(...match.slice(1));
      window.scrollTo(0, 0);
      return;
    }
  }
  location.hash = '#/games';
}

window.addEventListener('hashchange', route);

/* ------------------------------------------------------------------ games */

async function renderGames() {
  viewTitle.textContent = 'Games';
  viewAction.innerHTML = '<button class="primary small" id="new-game">New game</button>';
  document.getElementById('new-game').onclick = newGame;

  const games = await attempt(() => api('/games'));
  if (!games) return;

  if (!games.length) {
    view.innerHTML = `<div class="empty">
      <p>No games yet.</p>
      <p class="muted">Start one when the first player sits down.</p>
    </div>`;
    return;
  }

  view.innerHTML = games.map((game) => `
    <a class="card row between" href="#/game/${game.id}"
       style="text-decoration:none;color:inherit">
      <div class="grow">
        <div class="row" style="gap:8px">
          <strong class="truncate">${esc(game.label)}</strong>
          ${game.status === 'live' ? '<span class="pill live">Live</span>' : ''}
          ${game.voided ? '<span class="pill">Discarded</span>' : ''}
        </div>
        <div class="muted">
          ${esc(shortDate(game.started_at))} &middot; ${game.player_count} player${game.player_count === 1 ? '' : 's'}
          ${blindsLabel(game) ? ' &middot; ' + esc(blindsLabel(game)) : ''}
          ${game.location ? ' &middot; ' + esc(game.location) : ''}
        </div>
      </div>
      <div style="text-align:right">
        <div class="money">${esc(money(game.pot_cents, game.currency))}</div>
        <div class="muted">bought in</div>
      </div>
    </a>`).join('');
}

async function newGame() {
  const values = await showModal({
    title: 'New game',
    submitLabel: 'Start game',
    fields: [
      { name: 'label', label: 'Name', value: `Game ${shortDate(new Date().toISOString())}` },
      { name: 'location', label: 'Where (optional)', placeholder: 'Kitchen table' },
      { name: 'currency', label: 'Currency', options: [
        { value: 'EUR', label: 'EUR €' },
        { value: 'USD', label: 'USD $' },
        { value: 'GBP', label: 'GBP £' },
      ] },
      { name: 'buy_in', label: 'Standard buy-in', inputmode: 'decimal', value: '50' },
      { name: 'blinds', label: 'Blinds', placeholder: '10/20', value: '' },
    ],
  });
  if (!values) return;

  const blinds = parseBlinds(values.blinds);
  const game = await attempt(() => api('/games', {
    method: 'POST',
    body: {
      label: values.label,
      location: values.location,
      currency: values.currency,
      default_buy_in_cents: parseMoney(values.buy_in) || 0,
      small_blind_cents: blinds.small,
      big_blind_cents: blinds.big,
    },
  }));
  if (game) location.hash = `#/game/${game.id}`;
}

/* ------------------------------------------------------- one live game */

async function renderGame(gameId) {
  const detail = await attempt(() => api(`/games/${gameId}`));
  if (!detail) { location.hash = '#/games'; return; }

  const { game, summary, transactions } = detail;
  const settlement = await attempt(() => api(`/games/${gameId}/settlement`));
  const players = await attempt(() => api('/players')) || [];
  const currency = game.currency;
  const seated = new Set(summary.results.map((r) => r.player_id));
  const anyCashedOut = summary.results.some((r) => r.cashed_out);

  viewTitle.textContent = game.label;
  viewAction.innerHTML = '<a href="#/games" class="muted" style="text-decoration:none">Back</a>';

  const onTable = summary.total_buy_in_cents - summary.total_cash_out_cents;

  view.innerHTML = `
    ${game.voided ? `<div class="banner warn">
        Discarded${game.void_reason ? ` &mdash; ${esc(game.void_reason)}` : ''}.
        Kept on the record, but not counted in anyone's capital.
      </div>` : ''}
    ${!game.voided && anyCashedOut && !summary.balanced
      ? `<div class="banner warn">${esc(summary.balance_message)}</div>` : ''}
    ${!game.voided && anyCashedOut && summary.balanced
      ? `<div class="banner ok">The books balance.</div>` : ''}

    <div class="card">
      <div class="row between">
        <div>
          <div class="muted">Bought in</div>
          <div class="headline" style="font-size:1.5rem">${esc(money(summary.total_buy_in_cents, currency))}</div>
        </div>
        <div style="text-align:right">
          <div class="muted">Still on the table</div>
          <div class="headline" style="font-size:1.5rem">${esc(money(onTable, currency))}</div>
        </div>
      </div>
      <div class="muted" style="margin-top:8px">
        ${blindsLabel(game) ? esc(blindsLabel(game)) + ' blinds' : ''}
        ${blindsLabel(game) && game.location ? ' &middot; ' : ''}
        ${game.location ? esc(game.location) : ''}
        ${game.status === 'closed'
          ? (blindsLabel(game) || game.location ? ' &middot; ' : '') + 'Closed' : ''}
      </div>
    </div>

    <h2>Players</h2>
    <div class="card" id="players-card">
      ${summary.results.length
        ? summary.results.map((r) => playerRow(r, game)).join('')
        : '<div class="muted">Nobody is seated yet.</div>'}
    </div>

    ${game.status === 'live' ? `
      <div class="row" style="gap:10px">
        <select id="seat-select" class="grow">
          <option value="">Seat a player…</option>
          ${players.filter((p) => !seated.has(p.id))
            .map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}
        </select>
        <button id="seat-btn">Seat</button>
      </div>
      <button class="ghost wide" id="new-player-btn" style="margin-top:10px">
        + New player
      </button>` : ''}

    ${settlement && anyCashedOut ? settlementSection(settlement) : ''}

    <h2>Log</h2>
    <div class="card">
      ${transactions.length
        ? transactions.slice().reverse().map((t) => `
            <div class="log-entry">
              <div class="grow truncate">
                <strong>${esc(t.player_name)}</strong>
                <span class="muted">${esc(t.kind.replace('_', '-'))}${t.note ? ' · ' + esc(t.note) : ''}</span>
              </div>
              <div class="row" style="gap:8px">
                ${signed(entrySign(t), currency)}
                ${game.status === 'live' && !game.voided
                  ? `<button class="icon-btn" data-del="${t.id}"
                             aria-label="Delete entry" title="Delete entry">×</button>` : ''}
              </div>
            </div>`).join('')
        : '<div class="muted">Nothing recorded yet.</div>'}
    </div>

    <div class="stack" style="margin-top:18px">
      ${game.voided
        ? `<button class="primary wide" id="restore-btn">Restore game</button>`
        : game.status === 'live'
          ? `<button class="primary wide" id="close-btn">Close game</button>`
          : `<button class="ghost wide" id="reopen-btn">Reopen game</button>`}

      ${!game.voided
        ? `<button class="danger wide" id="void-btn">Discard game</button>` : ''}
      <button class="danger wide" id="delete-btn">Delete game permanently</button>
    </div>`;

  bindGameActions(gameId, game, summary, transactions);
}

function playerRow(result, game) {
  const currency = game.currency;
  const live = game.status === 'live';
  const buyInLabel = game.default_buy_in_cents
    ? `+ ${money(game.default_buy_in_cents, currency)}`
    : '+ Buy-in';
  return `
    <div class="player-row">
      <div class="grow">
        <div class="name truncate">${esc(result.name)}</div>
        <div class="muted">
          in ${esc(money(result.buy_in_cents, currency))}
          ${result.cashed_out ? ' · out ' + esc(money(result.cash_out_cents, currency)) : ''}
          ${result.adjustment_cents ? ' · adj ' + esc(money(result.adjustment_cents, currency)) : ''}
        </div>
      </div>
      <div style="text-align:right;min-width:76px">
        ${result.cashed_out ? signed(result.net_cents, currency) : '<span class="muted">playing</span>'}
      </div>
      ${live ? `
        <div class="row" style="gap:6px">
          ${game.default_buy_in_cents
            ? `<button class="small primary" data-quickbuy="${result.player_id}">${esc(buyInLabel)}</button>`
            : ''}
          <button class="small" data-buyin="${result.player_id}"
                  title="Custom buy-in">${game.default_buy_in_cents ? '…' : esc(buyInLabel)}</button>
          <button class="small" data-cashout="${result.player_id}">Cash out</button>
        </div>` : ''}
    </div>`;
}

function settlementSection(settlement) {
  if (!settlement.balanced) {
    return `<h2>Settle up</h2>
      <div class="card"><div class="muted">${esc(settlement.message)}</div></div>`;
  }
  return `
    <h2>Settle up</h2>
    <div class="card">
      <div class="muted" style="margin-bottom:8px">${esc(settlement.message)}</div>
      ${settlement.payments.map((p) => `
        <div class="log-entry">
          <div class="grow truncate">
            <strong>${esc(p.from_name)}</strong>
            <span class="muted">pays</span>
            <strong>${esc(p.to_name)}</strong>
          </div>
          <span class="money">${esc(money(p.amount_cents, settlement.currency))}</span>
        </div>`).join('')}
    </div>`;
}

function bindGameActions(gameId, game, summary, transactions) {
  const nameOf = (id) => (summary.results.find((r) => r.player_id === id) || {}).name || 'player';

  async function post(body) {
    const result = await attempt(() =>
      api(`/games/${gameId}/transactions`, { method: 'POST', body }));
    if (!result) return;

    renderGame(gameId);
    const what = body.kind === 'buy_in' ? 'Buy-in' : 'Cash-out';
    toast(`${what} ${money(body.amount_cents, game.currency)} — ${nameOf(body.player_id)}`);
  }

  view.querySelectorAll('[data-quickbuy]').forEach((button) => {
    button.onclick = () => post({
      player_id: Number(button.dataset.quickbuy),
      kind: 'buy_in',
      amount_cents: game.default_buy_in_cents,
    });
  });

  view.querySelectorAll('[data-buyin]').forEach((button) => {
    button.onclick = async () => {
      const playerId = Number(button.dataset.buyin);
      const values = await showModal({
        title: `Buy-in — ${nameOf(playerId)}`,
        submitLabel: 'Add buy-in',
        fields: [{
          name: 'amount', label: 'Amount', inputmode: 'decimal',
          value: game.default_buy_in_cents ? (game.default_buy_in_cents / 100).toFixed(2) : '',
        }],
      });
      if (!values) return;
      const cents = parseMoney(values.amount);
      if (!cents) return toast('Enter an amount', { error: true });
      post({ player_id: playerId, kind: 'buy_in', amount_cents: cents });
    };
  });

  view.querySelectorAll('[data-cashout]').forEach((button) => {
    button.onclick = async () => {
      const playerId = Number(button.dataset.cashout);
      const values = await showModal({
        title: `Cash out — ${nameOf(playerId)}`,
        message: 'Count the chips they are leaving with. Zero is fine.',
        submitLabel: 'Record cash-out',
        fields: [{ name: 'amount', label: 'Chips counted', inputmode: 'decimal', value: '' }],
      });
      if (!values) return;
      const cents = parseMoney(values.amount);
      if (cents === null || cents < 0) return toast('Enter an amount', { error: true });
      post({ player_id: playerId, kind: 'cash_out', amount_cents: cents });
    };
  });

  view.querySelectorAll('[data-del]').forEach((button) => {
    button.onclick = async () => {
      if (!await confirmModal('Delete entry?', 'This removes it from the ledger.', 'Delete')) return;
      const ok = await attempt(() => api(`/transactions/${button.dataset.del}`, { method: 'DELETE' }));
      if (ok) { renderGame(gameId); toast('Entry deleted'); }
    };
  });

  const seatButton = document.getElementById('seat-btn');
  if (seatButton) {
    seatButton.onclick = async () => {
      const select = document.getElementById('seat-select');
      if (!select.value) return;
      const name = select.options[select.selectedIndex].textContent;
      const ok = await attempt(() => api(`/games/${gameId}/players`, {
        method: 'POST', body: { player_id: Number(select.value) },
      }));
      if (ok) { renderGame(gameId); toast(`${name} seated`); }
    };
  }

  const newPlayerButton = document.getElementById('new-player-btn');
  if (newPlayerButton) {
    newPlayerButton.onclick = async () => {
      const player = await createPlayer();
      if (!player) return;
      const ok = await attempt(() => api(`/games/${gameId}/players`, {
        method: 'POST', body: { player_id: player.id },
      }));
      if (ok) { renderGame(gameId); toast(`${player.name} added and seated`); }
    };
  }

  const closeButton = document.getElementById('close-btn');
  if (closeButton) {
    closeButton.onclick = async () => {
      const pending = summary.awaiting_cash_out;
      if (pending.length) {
        const proceed = await confirmModal(
          'Still playing',
          `${pending.join(', ')} ${pending.length === 1 ? 'has' : 'have'} not cashed out yet.`,
          'Carry on anyway');
        if (!proceed) return;
      }
      try {
        await api(`/games/${gameId}/close`, { method: 'POST', body: { force: false } });
        renderGame(gameId);
        toast('Game closed — results are on the Players tab');
      } catch (error) {
        // The books do not balance. Say so plainly rather than closing over it.
        const force = await confirmModal('Close anyway?', error.message, 'Close anyway');
        if (!force) return;
        const ok = await attempt(() => api(`/games/${gameId}/close`, {
          method: 'POST', body: { force: true },
        }));
        if (ok) { renderGame(gameId); toast('Game closed, books left unbalanced'); }
      }
    };
  }

  const reopenButton = document.getElementById('reopen-btn');
  if (reopenButton) {
    reopenButton.onclick = async () => {
      const ok = await attempt(() => api(`/games/${gameId}/reopen`, { method: 'POST' }));
      if (ok) { renderGame(gameId); toast('Game reopened'); }
    };
  }

  const voidButton = document.getElementById('void-btn');
  if (voidButton) {
    voidButton.onclick = async () => {
      const proceed = await confirmModal(
        'Discard this game?',
        'It stays on the record but stops counting towards anyone’s capital. '
        + 'You can restore it later.',
        'Discard');
      if (!proceed) return;
      const ok = await attempt(() => api(`/games/${gameId}/void`, {
        method: 'POST', body: { reason: '' },
      }));
      if (ok) { renderGame(gameId); toast('Game discarded — no longer counted'); }
    };
  }

  const restoreButton = document.getElementById('restore-btn');
  if (restoreButton) {
    restoreButton.onclick = async () => {
      const ok = await attempt(() => api(`/games/${gameId}/restore`, { method: 'POST' }));
      if (ok) { renderGame(gameId); toast('Game restored — counting again'); }
    };
  }

  const deleteButton = document.getElementById('delete-btn');
  if (deleteButton) {
    deleteButton.onclick = async () => {
      // Name what is about to be destroyed. "Are you sure?" on its own gets
      // clicked through; a count of entries and the money involved does not.
      const entries = transactions.length;
      const damage = entries
        ? `${entries} entr${entries === 1 ? 'y' : 'ies'} and `
          + `${money(summary.total_buy_in_cents, game.currency)} of buy-ins`
        : 'nothing — no money was ever recorded against it';
      const proceed = await confirmModal(
        'Delete this game permanently?',
        `This erases ${damage}. It cannot be undone. `
        + 'Discard instead if you only want it to stop counting.',
        'Delete permanently');
      if (!proceed) return;
      const ok = await attempt(() => api(`/games/${gameId}`, { method: 'DELETE' }));
      if (ok) { location.hash = '#/games'; toast('Game deleted'); }
    };
  }
}

async function createPlayer() {
  const values = await showModal({
    title: 'New player',
    submitLabel: 'Add player',
    fields: [{ name: 'name', label: 'Name', placeholder: 'Their name' }],
  });
  if (!values || !values.name.trim()) return null;
  return attempt(() => api('/players', { method: 'POST', body: { name: values.name } }));
}

/* ---------------------------------------------------------------- players */

async function renderPlayers() {
  viewTitle.textContent = 'Players';
  viewAction.innerHTML = '<button class="primary small" id="add-player">Add</button>';
  document.getElementById('add-player').onclick = async () => {
    const player = await createPlayer();
    if (player) { renderPlayers(); toast(`${player.name} added`); }
  };

  const [statsList, players] = await Promise.all([
    attempt(() => api('/players/stats')),
    attempt(() => api('/players')),
  ]);
  if (!statsList || !players) return;

  const played = new Set(statsList.map((s) => s.player_id));
  const unplayed = players.filter((p) => !played.has(p.id));

  view.innerHTML = `
    ${statsList.length ? statsList.map(playerStatsCard).join('') : `
      <div class="empty">
        <p>No finished games yet.</p>
        <p class="muted">Capital is counted once a game is closed — chips
        still on the table are not winnings.</p>
      </div>`}

    ${unplayed.length ? `
      <h2>Not played yet</h2>
      <div class="card">
        ${unplayed.map((p) => `<div class="player-row"><div class="grow">${esc(p.name)}</div></div>`).join('')}
      </div>` : ''}

    <h2>Your data</h2>
    <div class="card stack">
      <div class="muted">The whole ledger, in a format you can open elsewhere.</div>
      <div class="row" style="gap:10px">
        <a class="btn grow" href="/api/export.csv" style="text-decoration:none;display:flex;align-items:center;justify-content:center">Export CSV</a>
        <a class="btn grow" href="/api/export.json" style="text-decoration:none;display:flex;align-items:center;justify-content:center">Export JSON</a>
      </div>
    </div>`;
}

function playerStatsCard(stats) {
  const currency = stats.sessions.length ? stats.sessions[0].currency : 'EUR';
  const roi = stats.roi === null ? '—' : (stats.roi * 100).toFixed(1) + '%';
  const streak = stats.streak.length > 1
    ? `${stats.streak.length} ${stats.streak.kind} nights in a row`
    : '';
  return `
    <div class="card">
      <div class="row between">
        <div class="grow">
          <div class="name" style="font-weight:650">${esc(stats.name)}</div>
          <div class="muted">
            ${stats.games_played} game${stats.games_played === 1 ? '' : 's'} ·
            ${stats.winning_sessions}W / ${stats.losing_sessions}L
            ${streak ? ' · ' + esc(streak) : ''}
          </div>
        </div>
        <div style="text-align:right">
          <div class="headline" style="font-size:1.35rem">${signed(stats.capital_cents, currency)}</div>
          <div class="muted">ROI ${esc(roi)}</div>
        </div>
      </div>
      ${capitalCurve(stats.sessions)}
      <div class="muted" style="margin-top:6px">
        Best ${esc(money(stats.best_night_cents, currency))} ·
        Worst ${esc(money(stats.worst_night_cents, currency))} ·
        Average ${esc(money(stats.average_net_cents, currency))} a night
      </div>
    </div>`;
}

/** A sparkline of running capital, with a zero line for reference. */
function capitalCurve(sessions) {
  if (sessions.length < 2) return '';
  const values = [0, ...sessions.map((s) => s.running_capital_cents)];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 300;
  const height = 44;
  const x = (i) => (i / (values.length - 1)) * width;
  const y = (value) => height - 3 - ((value - min) / span) * (height - 6);

  const line = values.map((value, i) => `${x(i).toFixed(1)},${y(value).toFixed(1)}`).join(' ');
  const zero = y(0).toFixed(1);
  const ends = values[values.length - 1] >= 0 ? 'var(--accent)' : 'var(--danger)';

  return `<svg class="curve" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"
               role="img" aria-label="Capital over time">
    <line x1="0" y1="${zero}" x2="${width}" y2="${zero}"
          stroke="var(--line)" stroke-width="1" stroke-dasharray="3 3"/>
    <polyline points="${line}" fill="none" stroke="${ends}"
              stroke-width="2" stroke-linejoin="round" stroke-linecap="round"
              vector-effect="non-scaling-stroke"/>
  </svg>`;
}

/* ------------------------------------------------------------------ odds */

const odds = {
  hole: [null, null],
  board: [null, null, null, null, null],
  opponents: 1,
  result: null,
  busy: false,
};

function oddsCards() {
  return [...odds.hole, ...odds.board].filter(Boolean);
}

function nextSlotIndex() {
  const all = [...odds.hole, ...odds.board];
  const index = all.indexOf(null);
  return index === -1 ? null : index;
}

function setSlot(index, card) {
  if (index < 2) odds.hole[index] = card;
  else odds.board[index - 2] = card;
}

async function renderOdds() {
  viewTitle.textContent = 'Odds';
  viewAction.innerHTML = '<button class="ghost small" id="clear-odds">Clear</button>';
  drawOdds();
}

function drawOdds() {
  const used = new Set(oddsCards());
  const next = nextSlotIndex();
  const boardCount = odds.board.filter(Boolean).length;

  const slot = (index, card) => {
    const isNext = index === next;
    const red = card && (card[1] === 'h' || card[1] === 'd');
    return `<button class="slot ${card ? 'filled' : ''} ${isNext ? 'next' : ''} ${red ? 'red' : ''}"
                    data-slot="${index}">
      ${card ? `<span>${esc(rankLabel(card[0]))}</span><span class="suit">${SUIT_GLYPH[card[1]]}</span>` : ''}
    </button>`;
  };

  view.innerHTML = `
    <div class="card">
      <div class="slots">
        <div class="slot-group">
          <span class="label">Your hand</span>
          ${slot(0, odds.hole[0])}${slot(1, odds.hole[1])}
        </div>
        <div class="slot-group">
          <span class="label">Flop</span>
          ${slot(2, odds.board[0])}${slot(3, odds.board[1])}${slot(4, odds.board[2])}
        </div>
        <div class="slot-group">
          <span class="label">Turn</span>${slot(5, odds.board[3])}
        </div>
        <div class="slot-group">
          <span class="label">River</span>${slot(6, odds.board[4])}
        </div>
      </div>
      <div class="deck">
        ${SUIT_ORDER.flatMap((suit) => RANK_ORDER.map((rank) => {
          const card = rank + suit;
          const red = suit === 'h' || suit === 'd';
          return `<button data-card="${card}"
                          class="${red ? 'red' : ''} ${used.has(card) ? 'used' : ''}">
            <span>${rankLabel(rank)}</span><span class="suit">${SUIT_GLYPH[suit]}</span>
          </button>`;
        })).join('')}
      </div>
    </div>

    <div class="card">
      <div class="field">
        <label for="opponents">Opponents still in the hand</label>
        <select id="opponents">
          ${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) =>
            `<option value="${n}" ${n === odds.opponents ? 'selected' : ''}>${n}</option>`).join('')}
        </select>
      </div>
    </div>

    ${oddsResultHtml(boardCount)}`;

  view.querySelectorAll('[data-card]').forEach((button) => {
    button.onclick = () => {
      const card = button.dataset.card;
      if (used.has(card)) return;
      const index = nextSlotIndex();
      if (index === null) return toast('Every slot is full — tap a card to clear it');
      setSlot(index, card);
      odds.result = null;
      drawOdds();
      computeOdds();
    };
  });

  view.querySelectorAll('[data-slot]').forEach((button) => {
    button.onclick = () => {
      const index = Number(button.dataset.slot);
      // Clearing a flop card leaves a hole, so collapse the board instead.
      if (index >= 2) {
        odds.board.splice(index - 2, 1);
        odds.board.push(null);
      } else {
        odds.hole[index] = null;
      }
      odds.result = null;
      drawOdds();
      computeOdds();
    };
  });

  document.getElementById('opponents').onchange = (event) => {
    odds.opponents = Number(event.target.value);
    computeOdds();
  };
  const clear = document.getElementById('clear-odds');
  if (clear) clear.onclick = () => {
    odds.hole = [null, null];
    odds.board = [null, null, null, null, null];
    odds.result = null;
    drawOdds();
  };
}

function oddsResultHtml(boardCount) {
  if (!odds.hole[0] || !odds.hole[1]) {
    return `<div class="empty">Tap two cards to fill your hand.</div>`;
  }
  if (boardCount === 1 || boardCount === 2) {
    return `<div class="empty">A flop is three cards — ${3 - boardCount} more to go.</div>`;
  }
  if (odds.busy && !odds.result) {
    return `<div class="empty">Working it out…</div>`;
  }
  if (!odds.result) return `<div class="empty">Working it out…</div>`;

  const r = odds.result;
  const bar = (label, value, cls) => `
    <div class="bar-row">
      <span class="bar-label">${label}</span>
      <span class="bar-track"><span class="bar-fill ${cls}" style="width:${(value * 100).toFixed(1)}%"></span></span>
      <span class="bar-value">${(value * 100).toFixed(1)}%</span>
    </div>`;

  return `
    <div class="card">
      <div class="row between" style="align-items:flex-end">
        <div>
          <div class="muted">Equity vs ${r.trials.toLocaleString()} simulated hands</div>
          <div class="headline pos">${(r.equity * 100).toFixed(1)}%</div>
        </div>
        <div style="text-align:right">
          <div class="muted">${esc(r.street)}</div>
          <div style="font-weight:650">${esc(r.made_hand)}</div>
        </div>
      </div>
      <div class="bars">
        ${bar('Win', r.win, 'win')}
        ${bar('Tie', r.tie, 'tie')}
        ${bar('Lose', r.lose, 'lose')}
      </div>
      <div class="muted">±${(r.margin_of_error * 100).toFixed(2)}% ·
        opponents assumed to hold any two cards</div>
    </div>

    ${r.draws && r.draws.length ? `
      <h2>Cards that improve you</h2>
      <div class="card">
        ${r.draws.map((d) => `
          <div class="draw-row">
            <div>
              <strong>${d.outs}</strong> to a ${esc(d.description)}
              <div class="draw-cards">${d.cards.map(prettyCard).join(' ')}</div>
            </div>
          </div>`).join('')}
      </div>` : ''}

    ${r.prices && r.prices.length ? `
      <h2>Is it worth calling?</h2>
      <div class="card">
        <div class="banner ${r.prices[0].worth_calling ? 'ok' : 'warn'}"
             style="margin:0 0 10px">${esc(r.biggest_call)}</div>
        <div class="muted" style="margin-bottom:6px">If someone bets…</div>
        ${r.prices.map((p) => `
          <div class="draw-row">
            <div>${esc(p.bet)}</div>
            <div class="row" style="gap:10px">
              <span class="muted">need ${(p.required_equity * 100).toFixed(0)}%</span>
              <strong class="${p.worth_calling ? 'pos' : 'neg'}" style="width:42px;text-align:right">
                ${p.worth_calling ? 'call' : 'fold'}
              </strong>
            </div>
          </div>`).join('')}
      </div>` : ''}`;
}

function prettyCard(card) {
  const red = card[1] === 'h' || card[1] === 'd';
  return `<span style="color:${red ? '#e07a7a' : 'inherit'}">${esc(rankLabel(card[0]))}${SUIT_GLYPH[card[1]]}</span>`;
}

let oddsTimer;
function computeOdds() {
  clearTimeout(oddsTimer);
  oddsTimer = setTimeout(runOdds, 180);
}

async function runOdds() {
  const board = odds.board.filter(Boolean);
  if (!odds.hole[0] || !odds.hole[1] || ![0, 3, 4, 5].includes(board.length)) {
    odds.result = null;
    drawOdds();
    return;
  }

  odds.busy = true;
  const body = {
    hole: [odds.hole[0], odds.hole[1]],
    board,
    opponents: odds.opponents,
    trials: 50000,
  };
  const result = await attempt(() => api('/odds', { method: 'POST', body }));
  odds.busy = false;
  if (result) {
    odds.result = result;
    drawOdds();
  }
}

/* ------------------------------------------------------------------ start */

route();
