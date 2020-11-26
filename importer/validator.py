
class Records1:  # Table level records
    def __init__(self):
        self.db = {}  # dict(index=dbobj) so each db table row has one dict entry
        self.xls = {}  # dict(index=dict(of xls rows) so each xls table row has one dict entry
        self.status = {}  # dict(index=[RowResult]) so each row represents either db table row or xls table row


class Validator:
    def validate_all(self):
        # TODO
        pass

    def xl_index_keys(self, headers, index_keys):
        # TODO
        pass

    def xl_record(self, xlrecord, config_schema):
        # TODO
        pass

    def xl_sheet(self, sheet):
        # TODO
        pass

    def dbrecord_exists(self, xlrecord):
        # TODO
        pass
