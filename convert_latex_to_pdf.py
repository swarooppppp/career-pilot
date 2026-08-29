#!/usr/bin/env python3
"""Compile a LaTeX source file into a PDF.

The LaTeX compiler runs in a temporary directory, keeping auxiliary files out
of the source and output directories.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a LaTeX (.tex) file to a PDF."
    )
    parser.add_argument("input", type=Path, help="Path to the LaTeX source file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Destination PDF path (defaults to the input file's directory)",
    )
    parser.add_argument(
        "--compiler",
        default="pdflatex",
        help="LaTeX compiler executable (default: pdflatex)",
    )
    return parser.parse_args()


def fail(message: str, exit_code: int = 1) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return exit_code


def compile_latex(input_path: Path, output_path: Path, compiler: str) -> int:
    input_path = input_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()

    if not input_path.exists():
        return fail(f"input file does not exist: {input_path}")
    if not input_path.is_file():
        return fail(f"input path is not a file: {input_path}")
    if input_path.suffix.lower() != ".tex":
        return fail(f"input file must have a .tex extension: {input_path}")

    compiler_path = shutil.which(compiler)
    if compiler_path is None:
        return fail(
            f"LaTeX compiler '{compiler}' was not found on PATH. "
            "Install TeX Live, MacTeX, or MiKTeX, or pass --compiler with "
            "an installed compiler."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="latex-build-") as build_dir:
        build_path = Path(build_dir)
        temporary_source = build_path / input_path.name
        shutil.copy2(input_path, temporary_source)
        temporary_pdf = build_path / f"{input_path.stem}.pdf"

        command = [
            compiler_path,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            temporary_source.name,
        ]
        result = subprocess.run(
            command,
            cwd=build_path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        if result.returncode != 0:
            print(result.stdout, file=sys.stderr, end="")
            return fail(
                f"{compiler} failed with exit code {result.returncode}",
                result.returncode,
            )
        if not temporary_pdf.exists():
            print(result.stdout, file=sys.stderr, end="")
            return fail("compiler completed without producing the expected PDF")

        shutil.copy2(temporary_pdf, output_path)

    print(f"PDF created: {output_path}")
    return 0


def main() -> int:
    args = parse_args()
    output_path = args.output or args.input.with_suffix(".pdf")
    return compile_latex(args.input, output_path, args.compiler)


if __name__ == "__main__":
    raise SystemExit(main())
