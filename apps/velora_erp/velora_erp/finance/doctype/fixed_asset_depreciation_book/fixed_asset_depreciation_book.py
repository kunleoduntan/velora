from velora import Document, throw, get_list

class FixedAssetDepreciationBook(Document):
    def validate(self):
        if not self.book_code or not self.book_name:
            throw("Book Code and Book Name are required.")
        if self.book_type not in ("Financial", "Tax", "Management"):
            throw("Select Financial, Tax or Management as the book type.")
        self.posts_to_gl = 1 if self.book_type == "Financial" else 0
        if self.book_type == "Financial" and not self.accounting_framework:
            throw("Select the accounting framework for the financial depreciation book.")
        if self.is_default:
            other = get_list("Fixed Asset Depreciation Book", filters={"is_default": 1, "disabled": 0}, fields=["name"], limit=10, ignore_permissions=True)
            if any(row["name"] != self.name for row in other):
                throw("Only one active default depreciation book is permitted in the company.")
