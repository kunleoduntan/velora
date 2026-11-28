from velora import Document, get_list, throw

class BoardPack(Document):
    def validate(self):
        if self.meeting and self.pack_version:
            versions = get_list("Board Pack", filters=[["meeting", "=", self.meeting], ["pack_version", "=", self.pack_version]], fields=["name"], limit=20)
            if any(row.get("name") != self.name for row in versions):
                throw("Pack Version must be unique for the selected Meeting.")
        seen_papers = set(); seen_sequence = set()
        for row in self.papers or []:
            if row.board_paper in seen_papers:
                throw("A Board Paper can only appear once in a Board Pack.")
            seen_papers.add(row.board_paper)
            if row.sequence in seen_sequence:
                throw("Board Pack paper sequence numbers must be unique.")
            seen_sequence.add(row.sequence)
            papers = get_list("Board Paper", filters=[["name", "=", row.board_paper]], fields=["meeting"], limit=1)
            if papers and papers[0].get("meeting") != self.meeting:
                throw("A Board Pack can only include papers for its own Meeting.")
        if self.pack_status in ("Generated", "Circulated") and not self.file_reference:
            throw("A Generated or Circulated Board Pack must have a file reference.")
        if self.pack_status == "Circulated" and not self.circulated_on:
            throw("A Circulated Board Pack must have a Circulation Date.")
