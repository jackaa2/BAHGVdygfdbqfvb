/**
 * GTA6 Clip Hub – Google Apps Script
 * Paste into the sheet: Extensions > Apps Script > replace everything > Save.
 * Then reload the sheet and click:  🎬 Clip Hub > 1. First-time setup
 *
 * What it does
 *  - Creates the Drive folders (in the Google account that runs setup).
 *  - Puts one-tap folder links in the Control Panel (row 2) and Account Styles tabs.
 *  - Moves a clip's raw file the moment you set YOUR DECISION:
 *        Approve -> 03_Approved     Reject -> 06_Rejected     Hold / blank -> 02_Screened
 *    and updates Pipeline Status.
 * It never deletes anything.
 */

// Everyone who approves clips. Setup gives each of them Editor access to the video folders.
// Run setup while signed in as jcompitelloyt@gmail.com (the account that should own the videos).
const TEAM = ['jcompitelloyt@gmail.com', 'compitellojack@gmail.com'];

const PANEL = 'Control Panel';
const STYLES = 'Account Styles';
const HEADER_ROWS = 3;
const COL = { ID: 1, RAWFILE: 9, DECISION: 13, DECIDED_BY: 14, STATUS: 27, NOTES: 29 };
const FOLDERS = ['00_Brand', '01_Raw', '02_Screened', '03_Approved', '04_Accounts', '05_Posted', '06_Rejected'];
const MOVE = {
  Approve: { folder: '03_Approved', status: 'Approved' },
  Reject:  { folder: '06_Rejected', status: 'Rejected' },
  Hold:    { folder: '02_Screened', status: 'Screened' },
  '':      { folder: '02_Screened', status: 'Screened' },
};

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
    const root = DriveApp.createFolder('GTA6 Clip Hub (Videos)');
    const ids = { ROOT: root.getId() };
    FOLDERS.forEach(n => (ids[n] = root.createFolder(n).getId()));
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
  writeLinks_(ids);
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'onDecisionEdit')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('onDecisionEdit').forSpreadsheet(SpreadsheetApp.getActive()).onEdit().create();
  ui.alert('Clip Hub is ready',
    'Folders are in Google Drive under "GTA6 Clip Hub (Videos)" and shared as Editor with: ' + TEAM.join(', ') +
    '. Links are in row 2 of the Control Panel. Approvals from any of you move files automatically.', ui.ButtonSet.OK);
}

function writeLinks_(ids) {
  const link = (id, label) => '=HYPERLINK("https://drive.google.com/drive/folders/' + id + '","' + label + '")';
  const ss = SpreadsheetApp.getActive();
  const panel = ss.getSheetByName(PANEL);
  panel.getRange(2, 4, 1, 10).setValues([[
    '📁 FOLDERS:',
    link(ids.ROOT, '📂 All'),
    link(ids['01_Raw'], '01 Raw'),
    link(ids['02_Screened'], '02 Screened'),
    link(ids['03_Approved'], '03 Approved'),
    link(ids['04_Accounts'], '04 Accounts'),
    link(ids['05_Posted'], '05 Posted'),
    link(ids['06_Rejected'], '06 Rejected'),
    link(ids['00_Brand'], '00 Brand'),
    '',
  ]]).setFontColor('#9fd3ff').setFontWeight('bold').setHorizontalAlignment('center');
  panel.getRange(3, COL.DECISION).setNote(
    'Pick Approve / Reject / Hold. The raw file moves to the matching Drive folder right away, ' +
    'and Pipeline Status updates. Use Filter views > "My Queue" to see only clips that need you.');
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
  const c1 = e.range.getColumn(), c2 = e.range.getLastColumn();
  if (COL.DECISION < c1 || COL.DECISION > c2) return;
  for (let r = Math.max(e.range.getRow(), HEADER_ROWS + 1); r <= e.range.getLastRow(); r++) processRow_(sh, r);
}

function resyncAll() {
  const sh = SpreadsheetApp.getActive().getSheetByName(PANEL);
  const last = sh.getLastRow();
  for (let r = HEADER_ROWS + 1; r <= last; r++) {
    if (sh.getRange(r, COL.ID).getValue()) processRow_(sh, r);
  }
}

function processRow_(sh, r) {
  const ids = JSON.parse(PropertiesService.getDocumentProperties().getProperty('FOLDERS') || '{}');
  if (!ids.ROOT) return;
  const decision = String(sh.getRange(r, COL.DECISION).getValue()).trim();
  const rule = MOVE[decision];
  if (!rule) return;
  const fileId = extractId_(sh.getRange(r, COL.RAWFILE));
  if (!fileId) return; // example rows / no file yet
  try {
    const file = DriveApp.getFileById(fileId);
    file.moveTo(DriveApp.getFolderById(ids[rule.folder]));
    const status = sh.getRange(r, COL.STATUS);
    const cur = String(status.getValue());
    if (!['Making Versions', 'Versions Ready', 'Posted'].includes(cur) || decision !== 'Approve') status.setValue(rule.status);
  } catch (err) {
    sh.getRange(r, COL.NOTES).setValue('⚠ Move failed: ' + err.message);
  }
}

function extractId_(cell) {
  const text = (cell.getFormula() || '') + ' ' + String(cell.getValue() || '');
  const m = text.match(/(?:\/d\/|id=|folders\/)([-\w]{20,})/) || text.match(/\b([-\w]{25,})\b/);
  return m ? m[1] : '';
}
