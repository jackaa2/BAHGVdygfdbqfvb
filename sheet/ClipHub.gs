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
const HEAD = { ID: 'Clip ID', RAWFILE: 'Raw File', DECISION: '✅ YOUR DECISION', DECIDED_BY: 'Decided By', STATUS: 'Status', NOTES: 'Notes' };
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
const MOVE = {
  Approve: { folder: '03_Approved', status: 'Approved' },
  Reject:  { folder: '06_Rejected', status: 'Rejected' },
  Hold:    { folder: '02_Screened', status: 'Screened' },
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
    link(ids['01_Raw'], '📥 1 New Clips'),
    link(ids['02_Screened'], '⏸ 2 On Hold'),
    link(ids['03_Approved'], '✅ 3 Approved'),
    link(ids['04_Accounts'], '📤 4 Ready to Post'),
    link(ids['05_Posted'], '📦 5 Posted'),
    link(ids['06_Rejected'], '❌ 6 Rejected'),
    link(ids['00_Brand'], '🎨 0 Brand Kit'),
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
  const c = cols_(sh);
  const c1 = e.range.getColumn(), c2 = e.range.getLastColumn();
  if (!c.DECISION || c.DECISION < c1 || c.DECISION > c2) return;
  for (let r = Math.max(e.range.getRow(), HEADER_ROWS + 1); r <= e.range.getLastRow(); r++) processRow_(sh, r, c);
}

function resyncAll() {
  const sh = SpreadsheetApp.getActive().getSheetByName(PANEL);
  const c = cols_(sh);
  const last = sh.getLastRow();
  for (let r = HEADER_ROWS + 1; r <= last; r++) {
    if (sh.getRange(r, c.ID).getValue()) processRow_(sh, r, c);
  }
}

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
      const later = ['Editing', 'Ready to Post', 'Posted'].includes(cur);
      if (!(later && decision === 'Approve')) status.setValue(rule.status);
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
