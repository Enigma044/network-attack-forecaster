// Plain-language definitions shown when hovering or focusing a dotted term.
export const GLOSSARY: Record<string, string> = {
  flow: 'One conversation between two computers, e.g. a browser fetching a page. The log records how long it lasted, how much was sent and a few technical flags.',
  window: 'A one-minute slice of time. Everything that starts inside it is summarised together.',
  state:
    'The network state S_t: 34 numbers describing one window — traffic volume, protocol mix, timing, packet and byte sizes, TCP flag rates, port usage and how many distinct hosts talk.',
  'world model':
    'A model that learns how the network state changes over time, P(S_t+1 | S_t), rather than just labelling traffic. Because it predicts the next state, it can imagine several steps into the future.',
  rollout:
    'Forward simulation: the world model predicts the next state, feeds that prediction back in, and repeats K times. Doing this many times with random draws gives a spread of possible futures.',
  K: 'How many future windows the model simulates (10 by default, i.e. the next 10 minutes).',
  'attack window': 'A window in which at least 5% of flows are labeled malicious in the dataset.',
  'infiltration probability':
    'How often an attack showed up in the futures the model imagined for the next K minutes. Read it as “how worried”, not as an exact chance.',
  threshold: 'The flag line. Above it, the dashboard raises an alert. We chose it on separate practice data, never on the day you are looking at.',
  baseline: 'A simple, well-known model (logistic regression) given exactly the same information. It has no sense of how things unfold over time, so it shows whether our extra machinery helps.',
  persistence:
    'A naive reference: "the future looks like right now". It needs the true labels, so it is not a usable detector, but it shows how much a forecast adds beyond ongoing attacks.',
  'early warning': 'An alert raised while the current window is still benign and an attack window does follow within K windows.',
  shapley:
    'Shapley values (the idea behind SHAP) split the forecast among the input features fairly: each value is the average change in the forecast when that feature is added, over random orderings. They add up to the difference from a "normal traffic" baseline.',
  'log-odds': 'log(p / (1 − p)). A +1 change multiplies the odds of an attack by e ≈ 2.7. Used because probabilities saturate near 0 and 1.',
  σ: 'Standard deviations from the average of the training traffic. +3σ means unusually high.',
  precision: 'Of the alerts raised, the share that were right.',
  recall: 'Of the real attack periods, the share that were caught.',
  f1: 'The balance of precision and recall (their harmonic mean). 1 is perfect.',
  fpr: 'False-positive rate: the share of quiet periods that still raised an alert.',
  'ATT&CK stage':
    'Where the activity sits in an intrusion: Reconnaissance → Initial Access → Lateral Movement → Command and Control → Exfiltration. Mapped from dataset labels; tentative.'
};
