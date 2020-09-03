import logging
import re
import pandas as pd
from enum import Enum, IntEnum
from django.conf import settings
from datetime import datetime
from box import Box, BoxList
from django.db.models import TextField, CharField, Model

from ..common import nm, Registry, ColumnCompare, Issue, RowResult, getdictvalue
import attr


class LOD(IntEnum):
    ALL_FULL = 0 # "ALL"  # Complete report with list of records including DB and XL records
    ALL_MID = 1 # "ALL without data"  # List of records with indexkey information but no DB and XL records
    MISMATCH = 2 # "Only Mismatch"  # List of mismatch records including DB and XL records
    SUMMARY = 3 # "Summary"  # stats only - total_records, same_records, xl_only, db_only, no_change, miscellaneous


class Status(str, Enum):
    XL = 'XL'
    DB = 'DB'
    MISMATCH = 'MISMATCH'
    NO_CHANGE = 'EQUAL'
    PENDING = 'PENDING'  # pending comparison
    CANNOT_COMPARE = 'CANNOT_COMPARE'


class FieldType(str, Enum):
    CONCRETE = 'CONCRETE'
    M2M = 'M2M'
    FKEY = 'FKEY'


@attr.s(auto_attribs=True)
class Record:
    """
    In-memory record used for comparison and updating DB record
    Below xl data states are important to keep in mind,
    1. NEW record -> Not available in DB but available in XL. `xl_record` is filled, `db_record` not filled
    2. MISSING record -> DB record not available in XL. `xl_record` not filled, `db_record` filled
    3. UPDATE record -> Change between XL & DB record. `xl_record` filled, `db_record` filled
    4. NO CHANGE record -> Same XL & DB record. `xl_record` filled, `db_record` blank

    IMP: For each reference record we will have in-memory Record provided dependent tables are loaded first.
    """

    xl_record: Box = None
    db_record: Model = None
    status: Status = Status.PENDING
    mismatches: BoxList = None  # Array of mismatch


@attr.s(auto_attribs=True)
class Mismatch:  # Per field mismatch object
    field: str
    type: FieldType
    status: Status
    message: str
    extra_info: object


@attr.s(auto_attribs=True)
class ImportableSheet:
    name: str
    config_filters: Box
    model: Model
    config_data: Box
    index_keys: BoxList
    records: Box
    total_db_records: int
    total_xl_records: int

    @classmethod
    def from_sheetdata(cls, sheetdata: Box):
        if not sheetdata:
            raise ValueError('Sheet_details missing')

        sheet_nm = getdictvalue(sheetdata, 'sheet_name', None)
        filters = getdictvalue(sheetdata, 'filters', None)
        data = getdictvalue(getdictvalue(sheetdata, 'dataset', None), 'data', None)
        model = getdictvalue(getdictvalue(sheetdata, 'dataset', None), 'model', None)
        index_keys = getdictvalue(getdictvalue(sheetdata, 'dataset', None), 'index_key', None)
        obj = cls(name=sheet_nm, model=model, config_data=data, config_filters=filters,
                  index_keys=index_keys, records=Box(default_box=True), total_db_records=0, total_xl_records=0)
        return obj

    def load_xl(self):
        xl_data = Registry.xlreader.get_xldata(self.name, self.index_keys)
        for idx, record in xl_data.items():
            self.records[idx] = Record(xl_record=record, status=Status.XL)
        self.total_xl_records = len(self.records)

    def compare(self, xl_record, db_record):
        """ Compares xl record vs db record.
         Logic:
         1. know xl record field, using parser resolve FKEY inplace of field but also stores the xl special field _originals
         2. compare FKEY values (read from _originals dictionary) with respective model values (Possible FKEY records are DIFFERENT records in xl and DB, then compare against both)
         3. compare all concrete fields AS IS
         """

        mismatches = BoxList()
        if not xl_record:
            mismatches.append(Mismatch(field="", type=None, status=Status.DB, message="", extra_info=None))
        else:  # compare each field value
            for field, value in xl_record.items():
                references = self.config_data[field].references  # TODO: HG: This can throw key error
                if references:
                    ref_model = ""
                    m2m_fields = [f.name for f in db_record._meta.many_to_many]
                    values = []
                    # fkey_fields = [f.name for f in db_record._meta.fields if f.many_to_one]
                    if field in m2m_fields:
                        values = [re.sub('^\* ', '', i) for i in value.rsplit('\n')]
                    else:
                        values.append(value)

                    for v in values:
                        refs = Box()
                        for idx, ref in enumerate(
                                references):  # We can have multiple references e.g. compdependency.component_version => [(componentversion, component.name), (componentversion, version)]
                            ref_model = ref[
                                0]  # We are good to use the ref[0] and keep overwriting it becoz now we only support $model starting refs. TODO: below logic complelets needs to be re-written to support model names in reference
                            ref_field = ref[1]
                            refs[ref_field] = v.split(' - ')[
                                idx]  # Reference values can be combination of multiple fields separated by ' - '

                        # IMP: Ideally we should pass values and search for record but as of now
                        # we have reference fields are same as reference model's index
                        # e.g. ref field ['name - version'] will be defined as ref model's index as well
                        #   hence it is easy to find the ref record from ref model's importable_sheet's
                        try:
                            ref_importer = Registry.importer.get_sheet(ref_model)
                            if not ref_importer:
                                if self.config_data[field].formatting.read_only:
                                    logging.info(f'Skipping comparison for field [{field}] with value [{value}], '
                                                 f'as its marked as read_only in config.'
                                                 f' Cannot get importer for its model [{ref_model}]')
                                else:
                                    mismatches.append(
                                        Mismatch(field=field, type=type(value), status=Status.CANNOT_COMPARE,
                                                 message=f'Cannot get importer for model [{ref_model}]',
                                                 extra_info=None))
                            else:
                                record = ref_importer.get_record_from_dict(refs)
                                if not record or record.status == Status.MISMATCH:
                                    mismatches.append(Mismatch(field=field, type=type(value), status=Status.MISMATCH,
                                                               message='no referenced record found' if not record else 'referenced record has MISMATCH',
                                                               extra_info=Box(reference_record=record)))
                        except KeyError as e:
                            msg = f"{self.model}.{field}'s value {value} - record not available in reference model" \
                                  f" {ref_model}. Exception: {e}"
                            logging.error(msg)
                            mismatches.append(Mismatch(field=field, type=type(value), status=Status.MISMATCH,
                                                       message=msg, extra_info=None))
                elif not hasattr(db_record, field):
                    mismatches.append(Mismatch(field=field, type=type(value), status=Status.XL,
                                               message=f'field: "{field}" doesnt exist in DB',
                                               extra_info=None))
                elif getattr(db_record, field) != type(getattr(db_record, field))(value):
                    mismatches.append(Mismatch(field=field, type=type(value), status=Status.MISMATCH,
                                               message=f'values differ, dbvalue: "{getattr(db_record, field)}" and xlsvalue: "{value}"',
                                               extra_info=None))

        return mismatches

    def load_compare(self):
        """
           Main function that callers should invoke to importer XLS data into DB.

           Reads XLS data and updates records in database for the respective table.
           This is generic function which relies on '_get_record()' to provide records
        """

        # 1. Read xls table and keep them inside records[idx].xl_record
        # 3. compare results and keep them inside records.compare_status
        self.load_xl()
        dbobjs = self.model.objects.all()
        self.total_db_records = len(dbobjs)
        for dbobj in dbobjs:
            idx = self.get_db_index(dbobj)
            record = self.records.setdefault(idx, Record(db_record=dbobj, status=Status.DB))
            record.db_record = dbobj
            record.mismatches = self.compare(record.xl_record, record.db_record)
            if not record.mismatches:
                # TODO: Nothing to insert in DB all well
                record.status = Status.NO_CHANGE
                pass
            else:
                # TODO: Update the database based on the flags
                record.status = Status.MISMATCH
                pass
        logging.info(f'import_data() completed for sheet [{self.name}], model [{nm(self.model)}]')

    def get_db_index(self, dbobj) -> str:
        """ Traverses references if index key has a reference """
        try:
            idx = ""
            for attr in self.index_keys:
                references = getdictvalue(getdictvalue(self.config_data, attr, None), 'references', None)
                if references:
                    for (ref_model, ref_field) in references:
                        # TODO: Handle if ref_field has multi-level fields. e.g. component.name
                        value = ""
                        obj = getattr(dbobj, attr)
                        for i in ref_field.split('.'):
                            obj = getattr(obj, i)
                        idx = str(obj) if not idx else idx + ' - ' + str(obj)
                else:
                    value = getattr(dbobj, attr)
                    idx = value if not idx else idx + ' - ' + value
            return idx
        except Exception as e:
            logging.critical(
                f"Couldn't get db index for table {nm(self.model)} with object [{dbobj}]. Exception: [{e}]")
            raise e

    def get_index(self, obj) -> str:
        """ Useful for cases where references need not be traversed """
        return ' - '.join([getattr(obj, attr) for attr in self.index_keys])

    def get_record_idx(self, idx):
        return self.records.get(idx, None)

    def get_record_from_dict(self, datadict: Box):
        # check if datadict has index keys if yes then get_record_idx(self, idx) else scan through all records :(
        dd = Box({k.split('.')[0]: v for k, v in
                  datadict.items()})  # for comparing the index keys we don't need to care about multi-level fields
        if not set(self.index_keys) - dd.keys():  # IMP: for multi-level reference fields excel field name is always
            return self.get_record_idx(self.get_index(dd))
        else:
            # TODO: See how to improve performance

            def xl_match(key, value):
                if getattr(record.xl_record, key.split('.')[
                    0]) == value:  # we only support first field name for multi-level field references (if its a reference field)
                    return True
                return False

            def db_match(key, value):
                obj = record.db_record
                for i in key.split('.'):
                    obj = getattr(obj, i)
                if obj == type(obj)(value):
                    return True
                return False

            for _, record in self.records.items():
                if record.status in [Status.XL, Status.NO_CHANGE]:
                    for key, value in datadict.items():
                        if not xl_match(key, value):
                            return None
                    return record
                elif record.status == Status.DB:
                    for key, value in datadict.items():  # TODO: HG: IMP: handle index key with . e.g. 'component.name'
                        if not db_match(key, value):
                            return None
                    return record
                elif record.status == Status.MISMATCH:
                    for key, value in datadict.items():
                        if not xl_match(key, value):
                            if not db_match(key, value):
                                return None
                    return record
            return None

    def get_report(self, lod: LOD) -> str:
        """
        Generates report data and return back
        :param lod: Level of details. See class LOD
        :return: str
        """
        keys = BoxList()
        statuses = BoxList()
        mismatches = BoxList()
        xl_records = BoxList()
        db_records = BoxList()
        issue_cntr = 0

        for (i, r) in self.records.items():
            if lod in (LOD.ALL_FULL, LOD.ALL_MID) or \
                    lod == LOD.MISMATCH and r.status != Status.NO_CHANGE:
                keys.append(i)
                statuses.append(r.status)
                mismatches.append(r.mismatches)

            if lod == LOD.ALL_FULL or \
                    lod == LOD.MISMATCH and r.status != Status.NO_CHANGE:
                xl_records.append(r.xl_record if r.xl_record else None)
                db_records.append({i: v for i, v in vars(r.db_record).items() if i != '_state'} if r.db_record else None)

            if r.status != Status.NO_CHANGE:
                issue_cntr+=1

        html_text = f'<p>Total xl_records: {self.total_xl_records}</p><p>Total DB records: {self.total_db_records}</p><p>Number of Issues: {issue_cntr}</p>'
        if lod != LOD.SUMMARY:
            data = dict({f'key{self.index_keys}': keys, 'status': statuses, 'mistmatch': mismatches})
            if xl_records:
                data['xl_record'] = xl_records
            if db_records:
                data['db_record'] = db_records
            html_text += pd.DataFrame(data).to_html(formatters={'status': lambda x: '<b>' + x + '</b>' if x != Status.NO_CHANGE else f'{x}'})
        html_text += '</p>'
        return html_text

    def create_record(self, datadict):
        """ Creates or Updates record """
        if not datadict:
            raise ValueError("Missing necessary data for creating object")

        filter = Box()
        for field in self.index_keys:
            filter[field] = datadict[field]
        # TODO: HG: Need to fetch KEY_ID for M2M and FKEY attributes
        self.model.update_or_create(filter, datadict)  # We always expect 1 record per filter


@attr.s(auto_attribs=True)
class Importer:
    importablemodels: Box

    @classmethod
    def from_registry(cls, dry_run, db_update, db_force_update):
        def validate_options_type(opts: Box, t):
            for o in opts.values():
                if not isinstance(o, t):
                    raise Exception(f'[{o}] option should be of type [{t}], instead received type: [{type(dry_run)}]')

        def validate_options_conflict(opts: Box):
            if opts.dry_run and (db_force_update or db_update):
                raise Exception(f'dry_run isnt supported with db_update or db_force_update')

        options = Box(dry_run=dry_run, db_force_update=db_force_update, db_update=db_update)
        validate_options_type(options, bool)
        validate_options_conflict(options)
        return Importer(importablemodels=Box(default_box=True))

    def get_sheet(self, name):
        return self.importablemodels[name]

    def import_sheets(self, options):
        datetime_str = datetime.now().strftime("%d-%m-%y %Ih.%Mm.%Ss%p")
        excel_file = options['xls_file']
        db_connection = settings.DATABASES.get('default')['NAME']
        cmd_opts = options
        html_text = f'<h2>Importer Report {datetime_str};</h2><p>Level of Details: {options["lod"]}</p>' \
                    f'<p>Excel file: {excel_file}</p><p>Database: {db_connection}</p><p>Command line option: {cmd_opts}</p><p>'

        for sheet_nm in Registry.parser.get_sheet_names(export_sequence=True):
            config = Registry.parser.get_sheet(sheet_nm)
            model_name = config.dataset.model_name.rsplit('.')[-1]
            self.importablemodels[model_name] = importable_sheet = ImportableSheet.from_sheetdata(config)
            logging.info(f'Validating sheet [{sheet_nm}]')
            importable_sheet.load_compare()
            excel_tab = importable_sheet.name
            db_table = nm(importable_sheet.model)
            html_text += f'<br></p><hr><h3>{model_name}</h3><p>Excel tab: {excel_tab}</p><p>DB Table: {db_table}</p><p>'
            html_text += importable_sheet.get_report(int(options["lod"]))
            html_text += '</p>'
        html_file = open(f'DET-report_{datetime_str}.html', 'w')
        html_text += f'<hr><p><em>This report is generated by&nbsp;</em><a href="https://github.com/hitengajjar/django-excel-transformer"><em>django-excel-transformer</em></a></p>'
        html_file.write(html_text)
        html_file.close()
