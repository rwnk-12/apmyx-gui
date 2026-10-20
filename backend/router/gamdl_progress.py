if __package__.startswith("backend."):
    from ..shared.progress import StreamProgress as GamdlProgress
else:
    from shared.progress import StreamProgress as GamdlProgress
