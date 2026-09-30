// Friendly names for CIC-IDS-2018 labels (the dataset's own spelling is kept in tooltips and tables of raw data).
const MAP: [RegExp, string][] = [
  [/^infilteration$/i, 'an insider infiltration'],
  [/^bot$/i, 'botnet activity'],
  [/^ftp-bruteforce$/i, 'FTP password guessing'],
  [/^ssh-bruteforce$/i, 'SSH password guessing'],
  [/^brute force -web$/i, 'web login guessing'],
  [/^brute force -xss$/i, 'cross-site scripting'],
  [/^sql injection$/i, 'SQL injection'],
  [/^ddos/i, 'a distributed denial-of-service flood'],
  [/^dos attacks-/i, 'a denial-of-service attack'],
  [/^portscan$/i, 'port scanning'],
  [/^benign$/i, 'normal traffic']
];

export function plainLabel(label: string): string {
  const hit = MAP.find(([re]) => re.test(label.trim()));
  return hit ? hit[1] : label;
}

/** "Infilteration (138), Benign (80)" → "insider infiltration (138), normal traffic (80)" */
export function plainLabelList(text: string): string {
  return text
    .split(', ')
    .map(part => {
      const m = part.match(/^(.*) \((\d+)\)$/);
      return m ? `${plainLabel(m[1]).replace(/^an? /, '')} (${m[2]})` : plainLabel(part);
    })
    .join(', ');
}
