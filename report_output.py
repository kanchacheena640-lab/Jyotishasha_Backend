"""Where generated report PDFs are written (F12-P3.5).

REPORT_OUTPUT_DIR overrides the directory, e.g. a temporary folder for local runs and tests. When it is unset
or blank the production default below is used, so deployed behaviour is unchanged.
"""
import os

REPORT_OUTPUT_DIR_ENV = "REPORT_OUTPUT_DIR"
DEFAULT_REPORT_OUTPUT_DIR = "/home/Jyotishasha/reports"


def report_output_dir() -> str:
    return os.environ.get(REPORT_OUTPUT_DIR_ENV, "").strip() or DEFAULT_REPORT_OUTPUT_DIR


def report_output_path(filename: str) -> str:
    return os.path.join(report_output_dir(), filename)
