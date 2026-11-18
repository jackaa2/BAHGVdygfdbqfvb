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
const HEAD = { TOPTEXT: '🎯 TOP TEXT', H1: 'Hook 1', ID: 'Clip ID', RAWFILE: 'Raw File', DECISION: '✅ YOUR DECISION', DECIDED_BY: 'Decided By', STATUS: 'Status', NOTES: 'Notes' };
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
// Status is automatic and only ever: New -> Pending (approved, captions being made) -> Ready to Post
const MOVE = {
  Approve: { folder: '03_Approved', status: 'Pending' },
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
      deleteRejected();
    }
    return;
  }
  const c = cols_(sh);
  const c1 = e.range.getColumn(), c2 = e.range.getLastColumn();
  if (c.TOPTEXT && c.TOPTEXT >= c1 && c.TOPTEXT <= c2 && c.DECISION) {
    for (let r = Math.max(e.range.getRow(), HEADER_ROWS + 1); r <= e.range.getLastRow(); r++) {
      const top = String(sh.getRange(r, c.TOPTEXT).getValue()).trim();
      if (top && String(sh.getRange(r, c.DECISION).getValue()).trim() === 'Approve') {
        kickEdit_();
        SpreadsheetApp.getActive().toast('Making the 6 versions now (3-5 min).', '🎬 Editing', 5);
        break;
      }
    }
  }
  if (!c.DECISION || c.DECISION < c1 || c.DECISION > c2) return;
  for (let r = Math.max(e.range.getRow(), HEADER_ROWS + 1); r <= e.range.getLastRow(); r++) processRow_(sh, r, c);
}

// ---- Delete all rejected clips (button = checkbox in Control Panel M2, or the menu) ----
const DELETE_BOX = 'P2';
const DELETED_TAB = 'Deleted Clips'; // hidden list so the robot never grabs a deleted clip again

function deleteRejected() {
  const ss = SpreadsheetApp.getActive();
  const sh = ss.getSheetByName(PANEL);
  const ui = SpreadsheetApp.getUi();
  const c = cols_(sh);
  const last = sh.getLastRow();
  if (last <= HEADER_ROWS || !c.DECISION) { ui.alert('No clips yet.'); return; }
  const n = sh.getLastColumn();
  const vals = sh.getRange(HEADER_ROWS + 1, 1, last - HEADER_ROWS, n).getValues();
  const forms = sh.getRange(HEADER_ROWS + 1, 1, last - HEADER_ROWS, n).getFormulas();
  const rows = [];
  vals.forEach((v, i) => { if (String(v[c.DECISION - 1]).trim() === 'Reject') rows.push(i); });
  if (!rows.length) { ui.alert('Nothing to delete', 'There are no rejected clips.', ui.ButtonSet.OK); return; }

  const ok = ui.alert('Are you sure?',
    'Delete ' + rows.length + ' rejected clip' + (rows.length > 1 ? 's' : '') + '?\n\n' +
    'Their rows are removed from the Control Panel and their videos are deleted for good ' +
    '(frees Drive space within 30 minutes). This cannot be undone.', ui.ButtonSet.YES_NO);
  if (ok !== ui.Button.YES) return;

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

  ui.alert('Done', 'Deleted ' + rows.length + ' rejected clip(s).' +
    (failed.length ? '\n\nCould not trash the video for: ' + failed.join(', ') : ''), ui.ButtonSet.OK);
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
  d.forEach((v, i) => {
    if (v[0] !== 'Approve' || st[i][0] === 'Ready to Post') return;
    if (String(top[i][0]).trim()) out.edit = true;
    else if (!String(h1[i][0]).trim()) out.hooks = true;
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
      if (!(later && decision === 'Approve')) status.setValue(rule.status);
    }
    if (decision === 'Approve') {
      const top = c.TOPTEXT ? String(sh.getRange(r, c.TOPTEXT).getValue()).trim() : '';
      if (top) kickEdit_();
      else { kick_('hooks.yml', 'LAST_HOOK_KICK');
             SpreadsheetApp.getActive().toast('Claude is writing 3 hooks (about 1 min). Then pick one in 🎯 TOP TEXT.', '✅ Approved', 6); }
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
