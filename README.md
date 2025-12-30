
# CSVChecker - A Robust CSV File Checker for Business Use

## 1. What is this tool?

CSVChecker is **not** a general-purpose CSV checker. It is specifically designed for **real-world, fragile CSV files** encountered in business operations. 

This tool is designed to handle CSV files with the following characteristics:

- **Encoding:** Windows-31J (cp932)
- **Line Endings:** CRLF is the standard, though LF-only files are also supported
- **Cells containing line breaks (LF or CRLF) inside double quotes**
- **Physical line numbers do not match CSV records** — meaning the number of lines in the file is not always equivalent to the number of records.

The tool processes **only the records**, ensuring that cell contents with embedded line breaks do not distort the structure.

## 2. Design Philosophy

The tool was developed with the following guiding principles:

- **Do not automatically make assumptions:** We do not automatically "fix" or adjust data without human oversight. Errors or inconsistencies are flagged and highlighted for manual review.
- **Non-interventionist approach:** This tool aims to **protect** users from making unintentional data changes. No automatic correction or modification of the CSV file is performed.
- **Strict Business Logic:** The tool adheres to strict, predefined business rules and ensures that CSV files comply with operational standards. 

### Why not auto-correct errors?
- **Human oversight is essential:** Errors in the data (such as missing or incorrectly formatted dates) require **human validation**. We do not take action automatically without confirmation that the data is correct.
- **No "fixing" data:** This tool doesn’t attempt to correct data but highlights discrepancies for review.

## 3. Why csv.reader + newline=""

The `csv.reader` function is used because it efficiently handles CSV data in a way that meets the following needs:

- **Row-by-row processing:** This ensures that data with embedded line breaks inside cells is handled correctly. We **do not** use line-based processing methods like `splitlines()` as they can distort CSV structure.
- **Consistent parsing:** By using `newline=""` and `StringIO`, we ensure that the correct line endings (CRLF or LF) are properly interpreted without causing issues with the data structure.

The key reason for choosing this approach is to **preserve the integrity of the CSV data**, particularly when cells contain line breaks.

## 4. Business Rules (Specifications)

This tool is built around **strict business rules** that check for specific issues in the CSV data. Here’s how the validation works:

### NG Check (Column 25 and Column 38)
- **Rule 1:** If Column 25 contains `"Z00014"` and Column 38 does not contain `"3000"` or `"5000"`, an error is raised.
- **Exception:** If Column 10 contains `"返品"` (meaning "Return"), then values of `"-3000"` and `"-5000"` in Column 38 are **allowed**.

### Date Check (Column 9 only)
- **Column 9:** Must be in the format `yyyy/mm/dd hh:mm:ss`. If the value is missing or improperly formatted, an **ERROR** is flagged.
- **Column 17:** This column is **ignored** and is **no longer checked** by the tool.

### Why Column 17 is no longer checked
- Column 17 was previously used to check for date consistency, but it has now been excluded from the validation process. The focus is solely on Column 9 for date validation.

## 5. Counts & Line Numbers

The tool processes CSV data row by row, and it's important to note the difference between **CSV records** and **physical lines**:

- **CSV records** refer to the number of actual data records (rows) in the CSV file, excluding the header.
- **Physical lines** refer to the actual lines in the CSV file, which may include additional formatting like blank lines or rows with embedded line breaks inside cells.

### Why physical line numbers are important:
- The **physical line number** is included in error reports to help users locate errors in the file.
- However, only **CSV records** (actual data rows) are used for validation, and these are what the tool reports on.

## 6. Security & Evidence

The tool performs the following security checks to ensure that the CSV data processing is secure:

- **Static Analysis:** Bandit is used to check for security vulnerabilities in the code.
- **Dependency Audit:** Pip-audit is used to ensure that dependencies do not contain known vulnerabilities.
- **SBOM (Software Bill of Materials):** The tool generates an SBOM in CycloneDX format to track dependencies and ensure compliance with security standards.

These steps ensure that the tool itself operates securely, without introducing vulnerabilities into your data processing pipeline.

## 7. Non-goals (Things This Tool Does Not Do)

This tool is **not** designed to:

- Automatically correct or fix data issues.
- Work with very large datasets (it is not intended for use with multi-gigabyte CSV files).
- Provide general-purpose CSV functionality like sorting, filtering, or editing.
- Handle CSVs that do not follow the specific business rules outlined above.

This tool is focused exclusively on **validating CSV files based on strict business rules** and ensuring compliance.

---

## Next Steps and Usage

1. **Upload a CSV file** via the Streamlit interface (drag and drop).
2. **Review any errors** flagged in the results.
3. **Download error reports** as CSV files for manual inspection.
