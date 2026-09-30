"""Network attack forecasting MVP (SIH 2026, problem 153).

Pipeline: flow CSV -> validation (schema) -> time windows (windows) -> sequences
-> LSTM / logistic-regression forecasts (models) -> explanation (explain).
"""

__version__ = "0.1.0"
