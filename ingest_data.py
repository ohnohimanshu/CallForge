"""
ingest_data.py
Run this script to load documents from a 'data/' folder into your Vector Database.

Architectural decision:
    .xlsx files are NOT run through UnstructuredExcelLoader +
    RecursiveCharacterTextSplitter like PDFs/docx. That combination
    flattens a whole sheet into one blob of text with no row/column
    boundaries, then slices it every 500 CHARACTERS with zero awareness
    that it's cutting through a table -- guaranteed to periodically split
    a course code from its own day/time/instructor and staple it onto a
    neighboring row's values instead. That mismatch (not the .xlsx format
    itself) was the actual cause of answers like "MS POOJA is scheduled
    for Friday" pulling together values that were never really connected.

    Instead, .xlsx is read with pandas so structure is preserved, and
    each ROW becomes its own chunk, built as explicit "column: value"
    pairs (e.g. "Day: Monday | 10:30-11:25: ITV305 AMIT") rather than
    unlabeled concatenated text -- so the day/time/course/instructor stay
    associated with each other by construction, not by hoping a character
    offset lands in the right place. Sheet name and source filename are
    included in every chunk too, since a workbook may have more than one
    timetable (e.g. one sheet per batch/semester) and losing that context
    would let a retrieval mix up which batch a class belongs to.

    Caveat: this assumes a fairly regular single-header-row-per-sheet
    layout. A spreadsheet with multiple stacked sub-tables in one sheet
    (a second header row appearing partway down, as college timetables
    sometimes have) will need the sheet split into separate ranges before
    ingestion, or the header-detection logic below extended to notice a
    second header row. If retrieved answers are still mixing up unrelated
    course batches after this change, that's the next thing to fix --
    ideally by inspecting the actual sheet layout rather than guessing.
"""
import os

import pandas as pd
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from services.rag_service import RagService


def _row_to_chunk_text(filename: str, sheet_name: str, headers: list[str], row: pd.Series) -> str | None:
    """
    Build one self-contained, labeled sentence for a single spreadsheet
    row -- e.g. "time table odd semester.xlsx - MSc CS1 | Day: Monday |
    10:30-11:25: ITV305 AMIT". Returns None for a row with no usable
    values (e.g. a blank separator row between sub-tables).
    """
    parts = []
    for header, value in zip(headers, row):
        if pd.isna(value):
            continue
        text_value = str(value).strip()
        if not text_value or text_value.lower() == "nan":
            continue
        header_label = str(header).strip() if header and "Unnamed" not in str(header) else None
        parts.append(f"{header_label}: {text_value}" if header_label else text_value)

    if not parts:  # no usable values in this row at all
        return None
    return " | ".join(parts)


def _load_xlsx_as_row_documents(filepath: str, filename: str) -> list[Document]:
    """
    Generic single-header-row Excel loader: emits one Document per
    non-empty row, using the first row of each sheet as column headers.
    Used as a FALLBACK for .xlsx files that don't match the specific
    merged-cell timetable layout handled by _load_timetable_xlsx below --
    see that function's docstring for why a generic approach isn't
    sufficient for a real merged-cell timetable grid.
    """
    documents: list[Document] = []
    sheets = pd.read_excel(filepath, sheet_name=None, header=0)
    for sheet_name, df in sheets.items():
        headers = list(df.columns)
        for _, row in df.iterrows():
            chunk_text = _row_to_chunk_text(filename, sheet_name, headers, row)
            if chunk_text is None:
                continue
            documents.append(
                Document(
                    page_content=chunk_text,
                    metadata={"source": filepath, "sheet": sheet_name},
                )
            )
    return documents


def _load_timetable_xlsx(filepath: str, filename: str) -> list[Document] | None:
    """
    Tailored parser for this specific merged-cell timetable layout
    (verified against the actual uploaded file):

        Row 0: title row ("Tentative Time table")
        Row 1: period NUMBERS (1, 2, 3, ... 10) in columns 2-11
        Row 2: the actual time-of-day RANGE for each period ("7:15-8:10",
               "8:10-9:05", ...) in columns 2-11 -- these two header rows
               together are what a single generic header=0 read would
               have collapsed into one, losing the actual clock times
        Row 3+: one row per class/batch. Column 0 (Day) is only populated
               on the FIRST row of each day's block due to merged cells
               in the source spreadsheet (e.g. "MONDAY" appears once,
               then is blank for the ~74 rows below it until "TUESDAY").
               Column 1 is the class/batch name (e.g. "CS Msc I",
               "BSc Bot I"). Columns 2-11 hold the actual course
               code/faculty/room for that class in that period.

    Forward-filling columns 0 and 1 reconstructs the day and class name
    for every row despite the merged-cell blanks, so each (day, class,
    period) combination can be turned into one fully self-contained
    chunk with the day, class, exact clock time, and course code/room
    all explicitly labeled and attached to each other -- e.g.:

        "Classes_schedule.xlsx | Day: Monday | Class: CS Msc I |
         Time 10:30-11:25: CSM014 GMS LT2"

    This is what fixed the earlier "MS POOJA is scheduled for Friday"
    style wrong answers -- those came from a generic loader that had no
    way to know which day/time/class a given cell of text belonged to.

    Returns None (falls back to the generic row loader above) if the
    expected header markers aren't found at their expected positions --
    e.g. if this is actually a different, non-timetable .xlsx, or the
    layout has changed -- rather than silently producing garbage from a
    layout this parser doesn't actually understand.
    """
    df = pd.read_excel(filepath, sheet_name=0, header=None)

    if df.shape[0] < 4 or df.shape[1] < 3:
        return None
    header_row = df.iloc[1].astype(str)
    duration_row = df.iloc[2].astype(str)
    if "Time" not in str(df.iloc[1, 1]) and "Class" not in str(df.iloc[1, 1]):
        return None
    if "Duration" not in str(df.iloc[2, 1]):
        return None

    period_cols = [c for c in range(2, df.shape[1]) if str(header_row[c]).strip().replace(".0", "").isdigit()]
    if not period_cols:
        return None

    day_col = df[0].ffill()
    class_col = df[1].ffill()

    documents: list[Document] = []
    for idx in range(3, len(df)):
        day_raw = str(day_col.iloc[idx]).strip()
        day = day_raw.split()[0].title() if day_raw and day_raw.lower() != "nan" else None
        class_name = str(class_col.iloc[idx]).strip()
        if not day or not class_name or class_name.lower() == "nan":
            continue
        for c in period_cols:
            value = df.iat[idx, c]
            if pd.isna(value):
                continue
            text_value = str(value).strip()
            if not text_value:
                continue
            duration = str(duration_row[c]).strip()
            # NOTE: the filename is deliberately NOT included in
            # page_content -- it only goes in metadata. Including it in
            # the text the LLM actually reads caused it to respond with
            # things like "please check Classes_schedule.xlsx yourself",
            # since the model latched onto the literal filename string as
            # if it were an instruction to defer to an external file,
            # rather than treating the content as data it already knows.
            chunk_text = f"Day: {day} | Class: {class_name} | Time {duration}: {text_value}"
            documents.append(
                Document(
                    page_content=chunk_text,
                    metadata={"source": filepath, "day": day, "class": class_name},
                )
            )
    return documents


def ingest_directory(folder_path: str):
    rag = RagService()
    # Used only for PDF/docx prose content, where character-based
    # splitting is appropriate. Excel rows bypass this entirely -- see
    # _load_xlsx_as_row_documents.
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)

    for filename in os.listdir(folder_path):
        filepath = os.path.join(folder_path, filename)
        print(f"Processing {filename}...")

        try:
            if filename.endswith(".pdf"):
                docs = PyPDFLoader(filepath).load()
                chunks = text_splitter.split_documents(docs)
            elif filename.endswith(".docx"):
                docs = Docx2txtLoader(filepath).load()
                chunks = text_splitter.split_documents(docs)
            elif filename.endswith(".xlsx"):
                chunks = _load_timetable_xlsx(filepath, filename)
                if chunks is None:
                    print(f"  ({filename} doesn't match the known timetable layout -- using generic row parser)")
                    chunks = _load_xlsx_as_row_documents(filepath, filename)
            else:
                continue

            rag.vector_store.add_documents(chunks)
            print(f"Added {len(chunks)} chunks from {filename}")

        except Exception as e:
            print(f"Error processing {filename}: {e}")


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    print("Put your .pdf, .docx, and .xlsx files in the 'data' directory.")
    ingest_directory("./data")