/**
 * GTA6 Clip Hub – Google Apps Script
 * Paste into the sheet: Extensions > Apps Script > replace everything > Save.
 * Then reload the sheet and click:  🎬 Clip Hub > 1. First-time setup
 *
 * What it does
 *  - Creates the Drive folders (in the Google account that runs setup).
 *  - Puts one-tap folder links in the Control Panel (row 2) and Account Styles tabs.
 *  - Moves a clip's raw file the moment you set YOUR DECISION:
 *        Approve -> 3 Approved   Reject -> 6 Rejected   Hold -> 2 On Hold   blank -> 1 New Clips
 *    and updates Status.
 * It never deletes anything.
 */

// Everyone who approves clips. Setup gives each of them Editor access to the video folders.
// Run setup while signed in as jcompitelloyt@gmail.com (the account that should own the videos).
const TEAM = ['jcompitelloyt@gmail.com', 'compitellojack@gmail.com'];

const PANEL = 'Control Panel';
const STYLES = 'Account Styles';
const HEADER_ROWS = 3;
// Columns are found by their header text in row 3, so moving columns never breaks this.
const HEAD = { TRIM: '✂️ TRIM', CUT: '✂️ CUT', LENGTH: 'Length (s)', SEND: '🚀 SEND', TOPTEXT: '🎯 TOP TEXT', H1: 'Hook 1', ID: 'Clip ID', RAWFILE: 'Raw File', DECISION: '✅ YOUR DECISION', DECIDED_BY: 'Decided By', STATUS: 'Status', NOTES: 'Notes' };
// Internal keys (stored at setup) -> folder names shown in Drive.
const NAMES = {
  '00_Brand': '0 - Brand Kit (logos + watermarks)',
  '01_Raw': '1 - New Clips (robot drops here)',
  '02_Screened': '2 - On Hold',
  '03_Approved': '3 - Approved (waiting for edits)',
  '04_Accounts': '4 - Ready to Post (by account)',
  '05_Posted': '5 - Posted',
  '06_Rejected': '6 - Rejected',
};
const ROOT_NAME = 'GTA6 Clip Hub - VIDEOS';
const FOLDERS = Object.keys(NAMES);
// Status is automatic: New -> Waiting for Hook (approved) -> Pending (hook picked, captions cooking) -> Ready to Post
const MOVE = {
  Approve: { folder: '03_Approved', status: 'Waiting for Hook' },
  Reject:  { folder: '06_Rejected', status: 'New' },
  Hold:    { folder: '02_Screened', status: 'New' },
  '':      { folder: '01_Raw', status: 'New' },
};

function cols_(sh) {
  const head = sh.getRange(HEADER_ROWS, 1, 1, sh.getLastColumn()).getValues()[0].map(h => String(h).trim());
  const c = {};
  Object.keys(HEAD).forEach(k => (c[k] = head.indexOf(HEAD[k]) + 1)); // 0 = not found
  return c;
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('🎬 Clip Hub')
    .addItem('1. First-time setup (folders + links + auto-move)', 'setup')
    .addItem('Re-check all decisions now', 'resyncAll')
    .addSeparator()
    .addItem('🗑 Delete all rejected clips…', 'deleteRejected')
    .addSeparator()
    .addItem('⏱ Connect robot timer (GitHub key)…', 'connectRobot')
    .addItem('▶ Run grabber now', 'runGrabberNow')
    .addSeparator()
    .addItem('✂️ Connect trimmer (after deploying web app)…', 'connectTrimmer')
    .addItem('📱 Set alert phone numbers (Verizon)…', 'setAlertPhones')
    .addToUi();
}

function setup() {
  const ui = SpreadsheetApp.getUi();
  const props = PropertiesService.getDocumentProperties();
  if (props.getProperty('FOLDERS')) {
    const r = ui.alert('Folders already exist', 'Setup already ran. Just reinstall the auto-move and links?', ui.ButtonSet.YES_NO);
    if (r !== ui.Button.YES) return;
  } else {
    const root = DriveApp.createFolder(ROOT_NAME);
    const ids = { ROOT: root.getId() };
    FOLDERS.forEach(n => (ids[n] = root.createFolder(NAMES[n]).getId()));
    const acc = DriveApp.getFolderById(ids['04_Accounts']);
    for (let i = 1; i <= 6; i++) ids['Account ' + i] = acc.createFolder('Account ' + i).getId();
    props.setProperty('FOLDERS', JSON.stringify(ids));
  }
  const ids = JSON.parse(props.getProperty('FOLDERS'));
  const me = (Session.getEffectiveUser().getEmail() || '').toLowerCase();
  const rootFolder = DriveApp.getFolderById(ids.ROOT);
  TEAM.filter(e => e.toLowerCase() !== me).forEach(e => {
    try { rootFolder.addEditor(e); } catch (err) { ui.alert('Could not share with ' + e + ': ' + err.message); }
  });
  renameFolders_(ids);
  writeLinks_(ids);
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'onDecisionEdit')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('onDecisionEdit').forSpreadsheet(SpreadsheetApp.getActive()).onEdit().create();
  ui.alert('Clip Hub is ready',
    'Folders are in Google Drive under "' + ROOT_NAME + '" and shared as Editor with: ' + TEAM.join(', ') +
    '. Links are in row 2 of the Control Panel. Approvals from any of you move files automatically.', ui.ButtonSet.OK);
}

function renameFolders_(ids) {
  try { DriveApp.getFolderById(ids.ROOT).setName(ROOT_NAME); } catch (e) {}
  FOLDERS.forEach(k => { try { DriveApp.getFolderById(ids[k]).setName(NAMES[k]); } catch (e) {} });
}

function writeLinks_(ids) {
  const link = (id, label) => '=HYPERLINK("https://drive.google.com/drive/folders/' + id + '","' + label + '")';
  const ss = SpreadsheetApp.getActive();
  const panel = ss.getSheetByName(PANEL);
  panel.getRange(2, 3, 1, 9).setValues([[
    '📁 FOLDERS:',
    link(ids.ROOT, '📂 All Videos'),
    link(ids['01_Raw'], '📥 New Clips'),
    link(ids['02_Screened'], '⏸ On Hold'),
    link(ids['03_Approved'], '✅ Approved'),
    link(ids['04_Accounts'], '📤 Ready to Post'),
    link(ids['05_Posted'], '📦 Posted'),
    link(ids['06_Rejected'], '❌ Rejected'),
    link(ids['00_Brand'], '🎨 Brand Kit'),
  ]]);
  const c = cols_(panel);
  if (c.DECISION) panel.getRange(HEADER_ROWS, c.DECISION).setNote(
    'Pick Approve / Reject / Hold. The raw file moves to the matching Drive folder right away ' +
    'and Status updates. Data > Filter views > "My Queue" shows only clips that need you.');
  const styles = ss.getSheetByName(STYLES);
  if (styles) {
    styles.getRange(1, 10).setValue('Drive Folder');
    const rows = [];
    for (let i = 1; i <= 6; i++) rows.push([link(ids['Account ' + i], '📁 Account ' + i)]);
    styles.getRange(2, 10, 6, 1).setValues(rows);
  }
}

// Installable trigger (set up by setup()). Fires when a person edits the sheet.
function onDecisionEdit(e) {
  if (!e || !e.range) return;
  const sh = e.range.getSheet();
  if (sh.getName() !== PANEL) return;
  if (e.range.getA1Notation() === DELETE_BOX) {
    if (e.range.getValue() === true) {
      e.range.setValue(false);
      const p = PropertiesService.getScriptProperties();
      const armed = Number(p.getProperty('DELETE_ARMED') || 0);
      if (Date.now() - armed < 30 * 1000) { p.deleteProperty('DELETE_ARMED'); deleteRejected_(true); }
      else {
        p.setProperty('DELETE_ARMED', String(Date.now()));
        const n = countRejected_();
        SpreadsheetApp.getActive().toast(n ? 'Tick the box AGAIN within 30 sec to delete ' + n + ' rejected clip(s) for good.' : 'No rejected clips.', '🗑 Are you sure?', 10);
      }
    }
    return;
  }
  const c = cols_(sh);
  const c1 = e.range.getColumn(), c2 = e.range.getLastColumn();
  if (c.TOPTEXT && c.TOPTEXT >= c1 && c.TOPTEXT <= c2 && c.DECISION && c.STATUS) {
    for (let r = Math.max(e.range.getRow(), HEADER_ROWS + 1); r <= e.range.getLastRow(); r++) refreshStatus_(sh, c, r);
  }
  if (c.SEND && c.SEND >= c1 && c.SEND <= c2 && c.DECISION) {
    for (let r = Math.max(e.range.getRow(), HEADER_ROWS + 1); r <= e.range.getLastRow(); r++) {
      const box = sh.getRange(r, c.SEND);
      if (box.getValue() !== true) {
        // once sent it stays sent
        const st = c.STATUS ? String(sh.getRange(r, c.STATUS).getValue()) : '';
        if (e.oldValue === 'TRUE' || st === 'Pending' || st === 'Ready to Post') {
          box.setValue(true);
          SpreadsheetApp.getActive().toast('Already sent: it can\'t be unsent.', '🚀 Sent', 5);
        }
        continue;
      }
      const approved = String(sh.getRange(r, c.DECISION).getValue()).trim() === 'Approve';
      const top = c.TOPTEXT ? String(sh.getRange(r, c.TOPTEXT).getValue()).trim() : '';
      if (!approved) { box.setValue(false); SpreadsheetApp.getActive().toast('Approve the clip first.', '🚀 Not yet', 5); continue; }
      if (!top) { box.setValue(false); SpreadsheetApp.getActive().toast('Pick a hook or type your own in 🎯 TOP TEXT first (or pick "(no top text)").', '🚀 Not yet', 7); continue; }
      const cut = c.CUT ? parseCut_(sh.getRange(r, c.CUT).getDisplayValue()) : null;
      if (cut === -1) { box.setValue(false); SpreadsheetApp.getActive().toast('✂️ CUT must look like 0:05-0:32 (or leave it blank).', '🚀 Not yet', 6); continue; }
      if (c.STATUS && String(sh.getRange(r, c.STATUS).getValue()) !== 'Ready to Post') sh.getRange(r, c.STATUS).setValue('Pending');
      kickEdit_();
      SpreadsheetApp.getActive().toast('Making the 6 versions now (3-5 min).', '🎬 Sent', 5);
    }
  }
  if (!c.DECISION || c.DECISION < c1 || c.DECISION > c2) return;
  for (let r = Math.max(e.range.getRow(), HEADER_ROWS + 1); r <= e.range.getLastRow(); r++) processRow_(sh, r, c);
}

// ---- Delete all rejected clips (button = checkbox in Control Panel M2, or the menu) ----
const DELETE_BOX = 'R2';
const DELETED_TAB = 'Deleted Clips'; // hidden list so the robot never grabs a deleted clip again

function countRejected_() {
  const sh = SpreadsheetApp.getActive().getSheetByName(PANEL);
  const c = cols_(sh);
  const n = sh.getLastRow() - HEADER_ROWS;
  if (n <= 0 || !c.DECISION) return 0;
  return sh.getRange(HEADER_ROWS + 1, c.DECISION, n, 1).getValues().filter(v => String(v[0]).trim() === 'Reject').length;
}

function deleteRejected() { deleteRejected_(false); }   // from the menu: asks with a popup

function deleteRejected_(confirmed) {
  const ss = SpreadsheetApp.getActive();
  const sh = ss.getSheetByName(PANEL);
  const say = (t, m) => { if (confirmed) ss.toast(m, t, 8); else SpreadsheetApp.getUi().alert(t, m, SpreadsheetApp.getUi().ButtonSet.OK); };
  const c = cols_(sh);
  const last = sh.getLastRow();
  if (last <= HEADER_ROWS || !c.DECISION) { say('🗑', 'No clips yet.'); return; }
  const n = sh.getLastColumn();
  const vals = sh.getRange(HEADER_ROWS + 1, 1, last - HEADER_ROWS, n).getValues();
  const forms = sh.getRange(HEADER_ROWS + 1, 1, last - HEADER_ROWS, n).getFormulas();
  const rows = [];
  vals.forEach((v, i) => { if (String(v[c.DECISION - 1]).trim() === 'Reject') rows.push(i); });
  if (!rows.length) { say('Nothing to delete', 'There are no rejected clips.'); return; }

  const ui = confirmed ? null : SpreadsheetApp.getUi();
  const ok = confirmed ? 'YES' : ui.alert('Are you sure?',
    'Delete ' + rows.length + ' rejected clip' + (rows.length > 1 ? 's' : '') + '?\n\n' +
    'Their rows are removed from the Control Panel and their videos are deleted for good ' +
    '(frees Drive space within 30 minutes). This cannot be undone.', ui.ButtonSet.YES_NO);
  if (!confirmed && ok !== ui.Button.YES) return;

  let log = ss.getSheetByName(DELETED_TAB);
  if (!log) {
    log = ss.insertSheet(DELETED_TAB);
    log.getRange(1, 1, 1, 4).setValues([['Clip ID', 'Clip link', 'Deleted', 'Video']]);
    log.hideSheet();
  }
  const logRows = [], failed = [];
  rows.forEach(i => {
    const row = vals[i], f = forms[i];
    const link = (f.join(' ').match(/https?:\/\/(?:www\.|clips\.)?(?:twitch\.tv|kick\.com)[^"\s]*/) || [''])[0];
    let video = 'no file';
    const fileId = c.RAWFILE ? extractId_(sh.getRange(HEADER_ROWS + 1 + i, c.RAWFILE)) : '';
    if (fileId) {
      try { DriveApp.getFileById(fileId).setTrashed(true); video = 'trashed'; }
      catch (err) { video = 'could not trash: ' + err.message; failed.push(row[c.ID - 1]); }
    }
    logRows.push([row[c.ID - 1], link, new Date(), video]);
  });
  log.getRange(log.getLastRow() + 1, 1, logRows.length, 4).setValues(logRows);
  rows.slice().reverse().forEach(i => sh.deleteRow(HEADER_ROWS + 1 + i));

  say('Done', 'Deleted ' + rows.length + ' rejected clip(s).' +
    (failed.length ? ' Could not trash the video for: ' + failed.join(', ') : ''));
}

// ---- Robot timer: kicks the GitHub robots on a schedule (backup for GitHub's own timer) ----
const GH_REPO = 'jackaa2/BAHGVdygfdbqfvb';

function connectRobot() {
  const ui = SpreadsheetApp.getUi();
  const r = ui.prompt('Connect robot timer',
    'Paste your GitHub key (starts with github_pat_). It is stored only inside this sheet\'s script.',
    ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;
  const token = r.getResponseText().trim();
  if (!/^(github_pat_|ghp_)/.test(token)) { ui.alert('That does not look like a GitHub key.'); return; }
  PropertiesService.getScriptProperties().setProperty('GH_TOKEN', token);
  const code = dispatch_('grab.yml');
  if (code !== 204) { ui.alert('GitHub said ' + code + '. Check the key has Actions: Read and write on gta6-clip-robot.'); return; }
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'robotTick')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('robotTick').timeBased().everyMinutes(10).create();
  PropertiesService.getScriptProperties().setProperty('LAST_GRAB', String(Date.now()));
  ui.alert('Robot timer connected', 'Grabber runs every 30 min, captions start right after you approve. ' +
    'A grab is running now.', ui.ButtonSet.OK);
}

function dispatch_(workflow) {
  const token = PropertiesService.getScriptProperties().getProperty('GH_TOKEN');
  if (!token) return 0;
  try {
    return UrlFetchApp.fetch('https://api.github.com/repos/' + GH_REPO + '/actions/workflows/' + workflow + '/dispatches', {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
      payload: JSON.stringify({ ref: 'main' }),
    }).getResponseCode();
  } catch (e) { return -1; }
}

function work_() {
  // what's waiting: approved clips without hooks (-> hooks robot), approved + hook picked (-> edit robot)
  const sh = SpreadsheetApp.getActive().getSheetByName(PANEL);
  const c = cols_(sh);
  const last = sh.getLastRow();
  const out = { hooks: false, edit: false };
  if (last <= HEADER_ROWS || !c.DECISION || !c.STATUS || !c.TOPTEXT) return out;
  const n = last - HEADER_ROWS;
  const d = sh.getRange(HEADER_ROWS + 1, c.DECISION, n, 1).getValues();
  const st = sh.getRange(HEADER_ROWS + 1, c.STATUS, n, 1).getValues();
  const top = sh.getRange(HEADER_ROWS + 1, c.TOPTEXT, n, 1).getValues();
  const h1 = c.H1 ? sh.getRange(HEADER_ROWS + 1, c.H1, n, 1).getValues() : top;
  const send = c.SEND ? sh.getRange(HEADER_ROWS + 1, c.SEND, n, 1).getValues() : top.map(() => [false]);
  d.forEach((v, i) => {
    if (v[0] !== 'Approve' || st[i][0] === 'Ready to Post') return;
    const t = String(top[i][0]).trim();
    if (t && send[i][0] === true) out.edit = true;
    if (!t && !String(h1[i][0]).trim()) out.hooks = true;
  });
  return out;
}

function robotTick() {
  const p = PropertiesService.getScriptProperties();
  // once a day: make sure GitHub hasn't switched the robots off (it does that after 60 quiet days)
  const day = new Date().toDateString();
  if (p.getProperty('LAST_KEEPALIVE') !== day) {
    ['grab.yml', 'edit.yml'].forEach(wf => ghCall_('put', '/actions/workflows/' + wf + '/enable'));
    p.setProperty('LAST_KEEPALIVE', day);
  }
  const last = Number(p.getProperty('LAST_GRAB') || 0);
  if (Date.now() - last >= 29 * 60 * 1000) {
    const code = dispatch_('grab.yml');
    if (code === 204) p.setProperty('LAST_GRAB', String(Date.now()));
    else timerProblem_(code);
  }
  const w = work_();
  if (w.hooks) dispatch_('hooks.yml');
  if (w.edit) dispatch_('edit.yml');
  try { checkAlerts_(); } catch (e) {}
}

function timerProblem_(code) {
  const msg = (code === 401 || code === 403 || code === 404)
    ? '⚠ Robot timer key expired or wrong. Fix: 🎬 Clip Hub > Connect robot timer (make a new GitHub key).'
    : '⚠ Robot timer could not reach GitHub (code ' + code + '). Will retry in 10 min.';
  try { SpreadsheetApp.getActive().getSheetByName(PANEL).getRange('G1').setValue(msg); } catch (e) {}
}

function ghCall_(method, path) {
  const token = PropertiesService.getScriptProperties().getProperty('GH_TOKEN');
  if (!token) return 0;
  try {
    return UrlFetchApp.fetch('https://api.github.com/repos/' + GH_REPO + path, {
      method: method, muteHttpExceptions: true,
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
    }).getResponseCode();
  } catch (e) { return -1; }
}

function runGrabberNow() {
  const code = dispatch_('grab.yml');
  SpreadsheetApp.getUi().alert(code === 204 ? 'Grabber started. New clips show up in 2-3 minutes.'
    : 'Could not start it (connect the robot timer first).');
}

function resyncAll() {
  const sh = SpreadsheetApp.getActive().getSheetByName(PANEL);
  const c = cols_(sh);
  const last = sh.getLastRow();
  for (let r = HEADER_ROWS + 1; r <= last; r++) {
    if (sh.getRange(r, c.ID).getValue()) processRow_(sh, r, c);
  }
}

// ---- Text alerts (Verizon email-to-text, free). Numbers live only in this script's settings. ----
function setAlertPhones() {
  const ui = SpreadsheetApp.getUi();
  const cur = PropertiesService.getScriptProperties().getProperty('ALERT_PHONES') || '';
  const r = ui.prompt('Text alerts', 'Verizon numbers to text when the robot needs fixing, comma separated (10 digits each).' +
    (cur ? '\nNow: ' + cur : ''), ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;
  const nums = r.getResponseText().split(',').map(x => x.replace(/\D/g, '')).filter(x => x.length === 10);
  if (!nums.length) { ui.alert('No valid 10-digit numbers found.'); return; }
  PropertiesService.getScriptProperties().setProperty('ALERT_PHONES', nums.join(','));
  sendAlert_('✅ GTA6 Clip Hub alerts are on. You will get a text here if the robot needs fixing.', true);
  ui.alert('Saved', 'Sent a test text to ' + nums.join(', ') + '.', ui.ButtonSet.OK);
}

function sendAlert_(msg, force) {
  const p = PropertiesService.getScriptProperties();
  const nums = (p.getProperty('ALERT_PHONES') || '').split(',').filter(Boolean);
  if (!nums.length) return;
  const key = 'ALERT_' + msg.slice(0, 40);
  if (!force && Date.now() - Number(p.getProperty(key) || 0) < 3 * 3600 * 1000) return;  // same alert max every 3 h
  p.setProperty(key, String(Date.now()));
  nums.forEach(n => MailApp.sendEmail(n + '@vtext.com', '', msg.slice(0, 150)));
}

function checkAlerts_() {
  const sh = SpreadsheetApp.getActive().getSheetByName(PANEL);
  const status = String(sh.getRange('G1').getValue());
  if (/FAILED|expired|could not reach/i.test(status)) sendAlert_('🚨 Clip robot: ' + status);
  else if (/⚠/.test(status) && /DRIVE \d+% FULL/.test(status)) sendAlert_('💾 Clip robot: Drive almost full. ' + status);
  // robot hasn't run for 2+ hours
  const m = status.match(/Robot · (\w+) (\d+):(\d+) (AM|PM)/);
  const last = Number(PropertiesService.getScriptProperties().getProperty('LAST_GRAB') || 0);
  if (last && Date.now() - last > 2 * 3600 * 1000) sendAlert_('🚨 Clip robot: grabber has not run for 2+ hours. Check the sheet.');
  // clips stuck after 3 failed edits
  const c = cols_(sh);
  if (c.NOTES) {
    const n = sh.getLastRow() - HEADER_ROWS;
    if (n > 0) {
      const bad = sh.getRange(HEADER_ROWS + 1, c.NOTES, n, 1).getValues().filter(v => /Edit failed \(try [3-9]/.test(v[0])).length;
      if (bad) sendAlert_('⚠ Clip robot: ' + bad + ' clip(s) failed to edit 3 times. See Notes column.');
    }
  }
}

// ---- Trim page (opens in a new tab from the ✂️ Trim link in each row) ----
// One-time: Deploy > New deployment > Web app (Execute as: Me, Who has access: Anyone with Google account),
// then 🎬 Clip Hub > ✂️ Connect trimmer.
const LINK_CELL = "'Account Styles'!L1";

function connectTrimmer() {
  const ui = SpreadsheetApp.getUi();
  let url = '';
  try { url = ScriptApp.getService().getUrl() || ''; } catch (e) {}
  const r = ui.prompt('Connect trimmer', 'Paste the Web app URL from Deploy > Manage deployments' +
    (url ? '\n(found: ' + url + ' — leave empty to use it)' : ''), ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;
  url = r.getResponseText().trim() || url;
  if (!/^https:\/\/script\.google\.com\/.+\/exec$/.test(url)) { ui.alert('That is not a web app URL (it ends with /exec).'); return; }
  // private key in the link instead of a Google sign-in (works with several Google accounts signed in)
  const p = PropertiesService.getScriptProperties();
  let key = p.getProperty('TRIM_KEY');
  if (!key) { key = Utilities.getUuid().replace(/-/g, ''); p.setProperty('TRIM_KEY', key); }
  SHEET_ID_();
  SpreadsheetApp.getActive().getRange(LINK_CELL).setValue(url + '?k=' + key);
  writeTrimLinks_();
  ui.alert('Trimmer connected', 'Every clip row now has a ✂️ Trim link.', ui.ButtonSet.OK);
}

function writeTrimLinks_() {
  const sh = SpreadsheetApp.getActive().getSheetByName(PANEL);
  const c = cols_(sh);
  const n = sh.getLastRow() - HEADER_ROWS;
  if (!c.TRIM || n <= 0) return;
  const ids = sh.getRange(HEADER_ROWS + 1, c.ID, n, 1).getValues();
  sh.getRange(HEADER_ROWS + 1, c.TRIM, n, 1).setFormulas(ids.map((v, i) => [v[0] ? trimFormula_(HEADER_ROWS + 1 + i) : '']));
}

function trimFormula_(r) {
  return '=IF($A' + r + '="","",HYPERLINK(' + LINK_CELL + '&"&id="&$A' + r + ',IF($' + colA1_(cols_(SpreadsheetApp.getActive().getSheetByName(PANEL)).CUT) + r + '="","✂️ Trim","✂️ "&$' + colA1_(cols_(SpreadsheetApp.getActive().getSheetByName(PANEL)).CUT) + r + ')))';
}

function colA1_(n) { let s = ''; while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); } return s; }

function doGet(e) {
  const key = PropertiesService.getScriptProperties().getProperty('TRIM_KEY');
  if (!key || !e || !e.parameter || e.parameter.k !== key) return HtmlService.createHtmlOutput('Link expired: open it from the sheet.');
  const id = String((e && e.parameter && e.parameter.id) || '');
  const sh = SpreadsheetApp.openById(SHEET_ID_()).getSheetByName(PANEL);
  const c = cols_(sh);
  const ids = sh.getRange(HEADER_ROWS + 1, c.ID, Math.max(sh.getLastRow() - HEADER_ROWS, 1), 1).getValues();
  const i = ids.findIndex(v => String(v[0]) === id);
  if (i < 0) return HtmlService.createHtmlOutput('Clip not found: ' + id);
  const r = HEADER_ROWS + 1 + i;
  const fileId = c.RAWFILE ? extractId_(sh.getRange(r, c.RAWFILE)) : '';
  const len = Number(c.LENGTH ? sh.getRange(r, c.LENGTH).getValue() : 0) || 60;
  const cut = c.CUT ? parseCut_(sh.getRange(r, c.CUT).getDisplayValue()) : null;
  const t = HtmlService.createTemplate(TRIM_HTML);
  t.id = id; t.fileId = fileId; t.len = Math.min(len, 600); t.k = e.parameter.k;
  t.a = cut && cut !== -1 ? cut[0] : 0;
  t.b = cut && cut !== -1 ? cut[1] : Math.min(len, 60);
  return t.evaluate().setTitle('✂️ Trim ' + id).addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function SHEET_ID_() {
  const p = PropertiesService.getScriptProperties();
  let id = p.getProperty('SHEET_ID');
  if (!id) { id = SpreadsheetApp.getActive().getId(); p.setProperty('SHEET_ID', id); }
  return id;
}

function saveTrim(id, a, b, k) {
  if (k !== PropertiesService.getScriptProperties().getProperty('TRIM_KEY')) throw new Error('not allowed');
  const sh = SpreadsheetApp.openById(SHEET_ID_()).getSheetByName(PANEL);
  const c = cols_(sh);
  const ids = sh.getRange(HEADER_ROWS + 1, c.ID, Math.max(sh.getLastRow() - HEADER_ROWS, 1), 1).getValues();
  const i = ids.findIndex(v => String(v[0]) === id);
  if (i < 0) throw new Error('clip not found');
  const r = HEADER_ROWS + 1 + i;
  if (!c.CUT) throw new Error('the ✂️ CUT column is missing in the Control Panel');
  a = Number(a); b = Number(b);
  if (!(b > a)) throw new Error('end must be after start');
  if (b - a > 60.05) throw new Error('max 1 minute');
  const len = Number((c.LENGTH && sh.getRange(r, c.LENGTH).getValue()) || 0);
  const full = a <= 0.05 && len && b >= len - 0.05;
  const cell = sh.getRange(r, c.CUT);
  cell.setNumberFormat('@');
  cell.setValue(full ? '' : mmss_(a) + '-' + mmss_(b));
  SpreadsheetApp.flush();
  return full ? 'Full clip' : mmss_(a) + '-' + mmss_(b);
}

function mmss_(x) {
  const m = Math.floor(x / 60), s = Math.round((x - m * 60) * 10) / 10;
  return m + ':' + (s < 10 ? '0' : '') + s;
}

// '0:05-0:32' -> [5, 32]; '' -> null; junk -> -1
function parseCut_(v) {
  const t = String(v || '').trim().replace(/^'/, '');
  if (!t) return null;
  const p = t.split(/\s*[-–]\s*/);
  if (p.length !== 2) return -1;
  const a = secs_(p[0]), b = secs_(p[1]);
  if (a === null || b === null || a < 0 || b < 0 || b <= a || b - a > 60) return -1;
  return [a, b];
}

const TRIM_HTML = `
<style>
 body{font-family:Arial,sans-serif;margin:10px auto;max-width:620px;background:#111;color:#eee}
 h3{margin:4px 0 10px}
 iframe{width:100%;height:290px;border:0;border-radius:8px;background:#000}
 .wrap{position:relative;height:36px;margin:18px 4px 6px}
 .wrap input{position:absolute;left:0;width:100%;pointer-events:none;-webkit-appearance:none;background:none;top:8px}
 .wrap input::-webkit-slider-thumb{pointer-events:all;-webkit-appearance:none;width:20px;height:28px;border-radius:5px;background:#ff8a2b;cursor:pointer;border:2px solid #fff}
 .track{position:absolute;top:18px;height:8px;width:100%;background:#333;border-radius:4px}
 .sel{position:absolute;top:18px;height:8px;background:#ff5596;border-radius:4px}
 .row{display:flex;justify-content:space-between;font-size:15px;font-weight:bold}
 button{margin-top:14px;width:100%;padding:12px;font-size:16px;font-weight:bold;border:0;border-radius:8px;background:#22c55e;color:#fff;cursor:pointer}
 .hint{font-size:12px;color:#aaa;margin-top:6px}
</style>
<h3>✂️ <?= id ?></h3>
<iframe src="https://drive.google.com/file/d/<?= fileId ?>/preview" allow="autoplay"></iframe>
<div class="wrap"><div class="track"></div><div class="sel" id="sel"></div>
 <input type="range" id="a" min="0" max="<?= len ?>" step="0.5" value="<?= a ?>">
 <input type="range" id="b" min="0" max="<?= len ?>" step="0.5" value="<?= b ?>">
</div>
<div class="row"><span>START <span id="ta"></span></span><span id="tl"></span><span>END <span id="tb"></span></span></div>
<div class="hint">Watch the clip above, drag the orange handles. Max 1 minute.</div>
<button id="save">✂️ Save trim</button>
<script>
 const A=document.getElementById('a'),B=document.getElementById('b'),L=<?= len ?>;
 const f=x=>{x=+x;const m=Math.floor(x/60),s=(x-m*60).toFixed(1).replace('.0','');return m+':'+(s<10?'0':'')+s};
 function upd(e){let a=+A.value,b=+B.value;
  if(b-a>60){ if(e&&e.target===A) b=a+60; else a=b-60; }
  if(b<=a+0.5){ if(e&&e.target===A) a=Math.max(0,b-0.5); else b=Math.min(L,a+0.5); }
  A.value=a;B.value=b;
  const sel=document.getElementById('sel');sel.style.left=(a/L*100)+'%';sel.style.width=((b-a)/L*100)+'%';
  ta.textContent=f(a);tb.textContent=f(b);tl.textContent=(b-a).toFixed(1)+'s';}
 A.oninput=upd;B.oninput=upd;upd();
 const btn=document.getElementById('save');
 btn.onclick=function(){btn.textContent='Saving…';btn.disabled=true;
  google.script.run
   .withSuccessHandler(t=>{btn.textContent='✅ Saved: '+t+'  (you can close this tab)';btn.style.background='#16a34a';btn.disabled=false;})
   .withFailureHandler(err=>{btn.textContent='❌ Not saved: '+(err&&err.message?err.message:err)+'  (tap to retry)';btn.style.background='#dc2626';btn.disabled=false;})
   .saveTrim('<?= id ?>',+A.value,+B.value,'<?= k ?>');};
</script>`;

// '0:05' / '5' / '1:02' -> seconds; '' -> null; junk -> -1
function secs_(v) {
  const t = String(v || '').trim().toLowerCase().replace(/s$/, '');
  if (!t) return null;
  const m = t.match(/^(\d+):(\d+(?:\.\d+)?)$/);
  if (m) return Number(m[1]) * 60 + Number(m[2]);
  return /^\d+(\.\d+)?$/.test(t) ? Number(t) : -1;
}

// Waiting for Hook -> Waiting to Send once approved + top text is set (and not sent yet)
function refreshStatus_(sh, c, r) {
  const st = sh.getRange(r, c.STATUS);
  const cur = String(st.getValue());
  if (cur === 'Pending' || cur === 'Ready to Post') return;
  if (String(sh.getRange(r, c.DECISION).getValue()).trim() !== 'Approve') return;
  const top = String(sh.getRange(r, c.TOPTEXT).getValue()).trim();
  st.setValue(top ? 'Waiting to Send' : 'Waiting for Hook');
}

function kick_(workflow, key) {
  // at most one start per 45 s per robot, even if several clips change at once
  const p = PropertiesService.getScriptProperties();
  if (Date.now() - Number(p.getProperty(key) || 0) < 45 * 1000) return;
  p.setProperty(key, String(Date.now()));
  dispatch_(workflow);
}

function kickEdit_() { kick_('edit.yml', 'LAST_EDIT_KICK'); }

function processRow_(sh, r, c) {
  const ids = JSON.parse(PropertiesService.getDocumentProperties().getProperty('FOLDERS') || '{}');
  if (!ids.ROOT || !c.DECISION || !c.RAWFILE) return;
  const decision = String(sh.getRange(r, c.DECISION).getValue()).trim();
  const rule = MOVE[decision];
  if (!rule) return;
  const fileId = extractId_(sh.getRange(r, c.RAWFILE));
  if (!fileId) return;
  try {
    DriveApp.getFileById(fileId).moveTo(DriveApp.getFolderById(ids[rule.folder]));
    if (c.STATUS) {
      const status = sh.getRange(r, c.STATUS);
      const cur = String(status.getValue());
      const later = cur === 'Ready to Post';
      if (!(later && decision === 'Approve')) {
        status.setValue(rule.status);
        if (decision !== 'Approve' && c.SEND) sh.getRange(r, c.SEND).setValue(false);
        if (decision === 'Approve' && c.TOPTEXT) refreshStatus_(sh, c, r);
      }
    }
    if (decision === 'Approve') {
      const h1 = c.H1 ? String(sh.getRange(r, c.H1).getValue()).trim() : '';
      if (!h1) kick_('hooks.yml', 'LAST_HOOK_KICK');
      SpreadsheetApp.getActive().toast('Claude is writing 3 hooks (about 1 min). Pick one in 🎯 TOP TEXT (or type your own), then tick 🚀 SEND.', '✅ Approved', 8);
    }
  } catch (err) {
    if (c.NOTES) sh.getRange(r, c.NOTES).setValue('⚠ Move failed: ' + err.message);
  }
}

function extractId_(cell) {
  const text = (cell.getFormula() || '') + ' ' + String(cell.getValue() || '');
  const m = text.match(/(?:\/d\/|id=|folders\/)([-\w]{20,})/) || text.match(/\b([-\w]{25,})\b/);
  return m ? m[1] : '';
}
