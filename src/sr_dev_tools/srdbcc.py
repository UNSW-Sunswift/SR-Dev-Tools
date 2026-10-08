from cantools import database
from typing import cast
import os
import argparse
import sys
import traceback
from sr_dev_tools.c_source import generate, camel_to_snake_case

def generate_c_source(
    infile: str,
    encoding: str | None = None,
    db_name: str | None = None,
    output_dir: str = "."
):
    db = cast(database.can.Database, database.load_file(infile, encoding=encoding))

    # If no name is specified, then the output file is the same as the input file
    if db_name is None:
        basename = os.path.basename(infile)
        db_name = os.path.splitext(basename)[0]
        db_name = camel_to_snake_case(db_name)

    h_filename = db_name + ".h"
    c_filename = db_name + ".c"

    header, source = generate(db, db_name, h_filename, c_filename)

    os.makedirs(output_dir, exist_ok=True)

    path_h = os.path.join(output_dir, h_filename)
    path_c = os.path.join(output_dir, c_filename)

    with open(path_h, "w") as f:
        f.write(header)

    with open(path_c, "w") as f:
        f.write(source)
    
    print(f"Successfully generated C source files {path_h} and {path_c}")

def main():
    parser = argparse.ArgumentParser(
        "SR-DBC-CodeGen",
        description="Generate C source code from a given database file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--database-name",
        help="The database name. Uses the stem of the input file name if not specified.",
    )
    parser.add_argument(
        "-e",
        "--encoding",
        help="File encoding.",
    )
    parser.add_argument(
        "-o",
        "--output-directory",
        default=".",
        help="Directory in which to write output files.",
    )
    parser.add_argument(
        "infile",
        help="Input database file.",
    )

    args = parser.parse_args()

    try:
        generate_c_source(
            args.infile,
            args.encoding,
            args.database_name,
            args.output_directory,
        )
    except Exception:
        traceback.print_exc()
        return 1

    return 0

if __name__ == "__main__":
    # print(sys.argv)

    if len(sys.argv) < 2:
        print("You need to provide a source dbc_file!")
        sys.exit(1)

    main()

    # generate_c_source("test_complex.dbc", db_name="can")
