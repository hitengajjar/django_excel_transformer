import logging
import re, json
from typing import Union

import pandas as pd
from enum import Enum, IntEnum
from django.conf import settings
from datetime import datetime
from box import Box, BoxList
from django.db.models import TextField, CharField, Model

from ..common import nm, Registry, getdictvalue
import attr


class LOD(IntEnum):
    ALL_FULL = 0  # "ALL"  # Complete report with list of records including DB and XL records
    ALL_MID = 1  # "ALL without data"  # List of records with indexkey information but no DB and XL records
    MISMATCH = 2  # "Only Mismatch"  # List of mismatch records including DB and XL records
    SUMMARY = 3  # "Summary"  # stats only - total_records, same_records, xl_only, db_only, no_change, miscellaneous


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
    refobjs: Box = None
    status: Status = Status.PENDING
    mismatches: BoxList = None  # Array of mismatch

    def to_json(self, field):
        """
        convert given field to json.
        :param field: string field. Applicable fields are "self", "xl_record", "db_record", "mismatches"
        :return: str
        """
        if field == 'self':
            obj = Box(xl_records=self.to_json("xl_record"),
                      db_records=self.to_json("db_record"),
                      mismatches=self.to_json("mismatches"),
                      status=self.status)
            return json.dumps(obj, sort_keys=True, default=str)
        elif field == 'xl_record':
            return self.xl_record.to_json() if self.xl_record else None
        elif field == 'db_record':
            db_data = {i: v for i, v in vars(self.db_record).items() if i != '_state'} if self.db_record else None
            return json.dumps(db_data, sort_keys=True, default=str) if db_data else None
        elif field == 'mismatches':
            json_str = '{"mismatches": ['
            for m in self.mismatches:
                json_str += m.to_json()
                json_str += ','
            json_str += ']}'
            return json_str


@attr.s(auto_attribs=True)
class Mismatch:  # Per field mismatch object
    field: str
    type: str
    status: Status
    message: str
    extra_info: object

    def to_json(self):
        return json.dumps(self.__dict__, sort_keys=True, default=str)


@attr.s(auto_attribs=True)
class Report:
    keys: BoxList = BoxList()
    xl_records: BoxList = BoxList()
    db_records: BoxList = BoxList()
    mismatches: BoxList = BoxList()
    statuses: BoxList = BoxList()
    db_update_status: BoxList = BoxList()
    list_idx: Box = Box()
    issue_cnt: int = 0


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
    report: Report

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
                  index_keys=index_keys, records=Box(), total_db_records=0, total_xl_records=0, report=Report())
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

         Returns tuple (mismatches, references)
         """

        mismatches = BoxList()
        refobjs = Box()
        if not xl_record:
            mismatches.append(Mismatch(field="", type=nm(None), status=Status.DB, message="", extra_info=None))
        else:  # compare each field value
            m2m_fields = [f.name for f in self.model._meta.many_to_many]
            for f, value in xl_record.items():
                references = self.config_data[f].references  # TODO: HG: This can throw key error
                if references:
                    ref_model = ""
                    if f in m2m_fields:
                        values = [re.sub('^\* ', '', i) for i in value.rsplit('\n')]
                    else:
                        values = [value]

                    for v in values:
                        refs = Box()
                        if len(references) != len(v.split(' - ')):
                            # we have invalid configuration for this reference and exported data doesn't honor this config.
                            # We cannot proceed with further checking of this record.
                            mismatches.append(
                                Mismatch(field=f, type=nm(type(value)), status=Status.CANNOT_COMPARE,
                                         message=f'Configuration mismatch for field [{f}] and xls data. Cannot get importer.',
                                         extra_info=None))
                            continue
                        for idx, ref in enumerate(references):
                            # We can have multiple references
                            # e.g. compdependency.component_version => [(componentversion,component.name),(componentversion,version)]
                            ref_model = ref[
                                0]  # We are good to use the ref[0] and keep overwriting it becoz now we only support $model starting refs. TODO: below logic needs to be re-written to support model names in reference in config.yaml
                            ref_field = ref[1]
                            refs[ref_field] = v.split(' - ')[
                                idx]  # ref values can be combination of multiple fields separated by ' - '

                        # IMP: Ideally we should pass values and search for record but as of now
                        # we have reference fields are same as reference model's index
                        # e.g. ref field ['name - version'] will be defined as ref model's index as well
                        #   hence it is easy to find the ref record from ref model's importable_sheet's
                        try:
                            # TODO: HG: Refactor need - pull out ref object checker in separate function
                            ref_importer = Registry.importer.get_sheet(ref_model)
                            if not ref_importer:
                                if self.config_data[f].formatting.read_only:
                                    logging.info(f'Skipping comparison for field [{f}] with value [{value}], '
                                                 f'as its marked as read_only in config.'
                                                 f' Cannot get importer for its model [{ref_model}]')
                                else:
                                    mismatches.append(
                                        Mismatch(field=f, type=nm(type(value)), status=Status.CANNOT_COMPARE,
                                                 message=f'Cannot get importer for model [{ref_model}]',
                                                 extra_info=None))
                            else:
                                ref_obj = ref_importer.get_record_from_dict(refs)
                                refobjs.setdefault(f, []).append(ref_obj)
                                if not ref_obj or ref_obj.status == Status.MISMATCH:
                                    mismatches.append(Mismatch(field=f, type=nm(type(value)), status=Status.MISMATCH,
                                                               message=f'no referenced record found; record wont be '
                                                                       f'create/updated in DB' if not ref_obj else
                                                               'referenced record has MISMATCH',
                                                               extra_info=Box(reference_record=ref_obj)))
                        except KeyError as e:
                            msg = f"{nm(self.model)}.{f}'s value {value} - record not available in reference model" \
                                  f" {ref_model}. Exception: {e}"
                            logging.error(msg)
                            mismatches.append(Mismatch(field=f, type=nm(type(value)), status=Status.MISMATCH,
                                                       message=msg, extra_info=None))
                elif db_record and not hasattr(db_record, f):
                    mismatches.append(Mismatch(field=f, type=nm(type(value)), status=Status.XL,
                                               message=f'field: "{f}" doesnt exist in DB',
                                               extra_info=None))
                elif db_record and getattr(db_record, f) != type(getattr(db_record, f))(value):
                    mismatches.append(Mismatch(field=f, type=nm(type(value)), status=Status.MISMATCH,
                                               message=f'values differ, dbvalue: "{getattr(db_record, f)}" and xlsvalue: "{value}"',
                                               extra_info=None))

            # We will fill in the refobjs which aren't part of xls but in DB
        return (refobjs, mismatches)

    def load_n_compare(self):
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
            (record.refobjs, record.mismatches) = self.compare(record.xl_record, record.db_record)
            if not record.mismatches:
                # TODO: Nothing to insert in DB all well
                record.status = Status.NO_CHANGE
                pass
            else:
                # TODO: Update the database based on the flags
                record.status = Status.MISMATCH
                pass
        for record in [r for _,r in self.records.items() if r.status == Status.XL]:
            (record.refobjs, record.mismatches) = self.compare(record.xl_record, None)  #Helps fill in the refobjs
        self._generate_compare_report()
        logging.info(f'import_data() completed for sheet [{self.name}], model [{nm(self.model)}]')

    def _generate_compare_report(self):
        """
        This is an interim report containing compare results.
        In dbupdate function, compare status changes.
        """
        report = self.report = Report(keys=BoxList(), statuses=BoxList(), mismatches=BoxList(), xl_records=BoxList(),
                                      db_records=BoxList(), db_update_status=BoxList(), list_idx=Box(), issue_cnt=0)

        for cnt, (i, r) in enumerate(self.records.items()):
            report.list_idx[i] = cnt
            report.keys.append(i)
            report.statuses.append(r.status)
            report.mismatches.append(r.to_json("mismatches"))
            report.xl_records.append(r.to_json("xl_record"))
            report.db_records.append(r.to_json("db_record"))
            if r.status != Status.NO_CHANGE:
                report.issue_cnt += 1

    def _update_report_db_status(self):
        """
        Interim report is updated with DB update status.
        This function expects interim report exists. TODO:
        """
        pass

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
        dd = Box()
        for k, v in datadict.items():
            k = k.split('.')[0]
            dd[k] = dd.get(k) + ' - ' + v if k in dd else v  # append v to existing dd[k] if k already part of dd

        if not set(self.index_keys) - dd.keys():  # IMP: multi-level reference fields excel field name is always same
            return self.get_record_idx(self.get_index(dd))
        else:
            # TODO: test below functionality

            def xl_match(k, v):
                if getattr(record.xl_record, k.split('.')[0]) == v:
                    # we only support first field name for multi-level field references
                    # (if its a reference field)
                    return True
                return False

            def db_match(k, v):
                obj = record.db_record
                for i in k.split('.'):
                    obj = getattr(obj, i)
                if obj == type(obj)(v):
                    return True
                return False

            for _, record in self.records.items():  # TODO: We have to consider m2m and fkeys while comparing with datadict items
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
        report = self.report
        keys = BoxList()
        statuses = BoxList()
        xl_records = BoxList()
        db_records = BoxList()
        mismatches = BoxList()

        for cnt, k in enumerate(self.report.keys):
            if lod in (LOD.ALL_FULL, LOD.ALL_MID) or (lod == LOD.MISMATCH and report.statuses[cnt] != Status.NO_CHANGE):
                keys.append(k)
                statuses.append(report.statuses[cnt])
                mismatches.append(report.mismatches[cnt])
                xl_records.append(report.xl_records[cnt] if lod == LOD.ALL_FULL or (
                        lod == LOD.MISMATCH and report.statuses[cnt] != Status.NO_CHANGE) else '-')
                db_records.append(report.db_records[cnt] if lod == LOD.ALL_FULL or (
                        lod == LOD.MISMATCH and report.statuses[cnt] != Status.NO_CHANGE) else '-')

        html_text = f'<p>Total xl_records: {self.total_xl_records}</p><p>Total DB records: {self.total_db_records}</p>'\
                    f'<p>Number of Issues: {report.issue_cnt}</p>'
        if lod != LOD.SUMMARY:
            data = dict({f'key{self.index_keys}': keys, 'status': statuses, 'db_update': None,
                         'mismatch': mismatches})
            if report.xl_records:
                data['xl_record'] = xl_records
            if report.db_records:
                data['db_record'] = db_records
            html_text += pd.DataFrame(data).to_html(
                formatters={'status': lambda x: '<b>' + x + '</b>' if x != Status.NO_CHANGE else f'{x}'})
        html_text += '</p>'
        return html_text

    def update_db(self, force_update=False):
        # Lets filter out all FKEYs and M2Ms
        m2m_fields = [f.name for f in self.model._meta.many_to_many]
        fkey_fields = [f.name for f in self.model._meta.fields if f.many_to_one]
        concrete_fields = [f.name for f in self.model._meta.concrete_fields if not f.many_to_one]

        err_records = BoxList()

        for i, r in self.records.items():  # TODO: HG: Db update record counter should be returned and updated in the logs
            if r.status == Status.NO_CHANGE:
                continue
            if r.status in (Status.XL, Status.MISMATCH):
                # We cannot create record if FKEY doesn't exist in referenced DB table or record has MISMATCH
                datadict = Box(default_box=False)
                filter = Box()
                invalid_ref = False
                for f, refobj in r.refobjs.items():
                    if not refobj or None in refobj:
                        v = ','.join([re.sub('^\* ', '', i) for i in r.xl_record[f].rsplit('\n')])
                        logging.error(
                            f" {nm(self.model)} - Wont update record [{i}] since "
                            f"[{f}={v}] has missing "
                            f"reference object. Ensure reference record exists either in DB or XLS")
                        invalid_ref = True
                        break

                if invalid_ref:
                    continue

                for f in self.index_keys:
                    if not r.refobjs or f not in r.refobjs:
                        filter[f] = getattr(r.xl_record, f)
                    else:
                        filter[f + '_id'] = r.refobjs[f][0].db_record.pk

                for f, v in r.xl_record.items():
                    if f in concrete_fields:
                        datadict[f] = v
                    elif r.refobjs:
                        if not force_update and r.refobjs[f].status != Status.NO_CHANGE:
                            logging.info(
                                f" {nm(self.model)} - Wont update record [{i}] since [{f}={r.xl_record[f]}] is ref "
                                f"field and it has a change. Use --force_update to update reference and this record.")
                            logging.info(f'Mismatch Reference Object - {r.refobjs[f]}')
                            invalid_ref = True
                            break
                        elif (f in fkey_fields) and (f in r.refobjs)\
                                and (force_update or r.refobjs[f][0].status == Status.MISMATCH):
                            datadict[f + '_id'] = r.refobjs[f][0].db_record.pk

                    else:
                        logging.error(f" {nm(self.model)} - Wont update record [{i}] since [{f}={r.xl_record[f]}] "
                                      f"is invalid (its neither concrete neither has reference")
                        invalid_ref = True
                        break

                if invalid_ref:
                    continue

                if force_update or r.status == Status.XL:  # don't update DB if record MISMATCH & force_update is False
                                                            # filter should always return 1 object if exists else 0
                    (dbobj, created) = self.model.objects.update_or_create(**filter, defaults=datadict)
                    r.db_record = dbobj
                    if r.refobjs:
                        for f in r.refobjs.keys() & m2m_fields:
                            getattr(dbobj, f).set([ro.db_record for ro in r.refobjs[f]]) # set will add all the records

                    dbobj.save()
                    r.status = Status.NO_CHANGE
                    logging.debug(f' {nm(self.model)}: {"created" if created else "updated"} object: {dbobj}')
                else:
                    err_records.append(r)

            elif r.status in (Status.MISMATCH, Status.XL) and force_update:
                # We need to update DB with XL values.
                #  Insert missing FKEYs in referenced table.
                pass


@attr.s(auto_attribs=True)
class Importer:
    importablemodels: Box
    options: Box

    @classmethod
    def from_registry(cls, xls_file, lod, report_nm, dry_run, db_update, db_force_update):
        def validate_options_type(opts: Box, t):
            for o in opts.values():
                if not isinstance(o, t):
                    raise Exception(f' [{o}] option should be of type [{t}], instead received type: [{type(o)}]')

        def validate_options_conflict(opts: Box):
            if opts.dry_run and (db_force_update or db_update):
                raise Exception(f'dry_run isnt supported with db_update or db_force_update')

        options = Box(dry_run=dry_run, db_force_update=db_force_update, db_update=db_update)
        validate_options_type(options, bool)
        options.update(dict(lod=lod, xls_file=xls_file, report_nm=report_nm))
        validate_options_conflict(options)
        return Importer(importablemodels=Box(default_box=True), options=options)

    def get_sheet(self, name):
        return self.importablemodels[name]

    def import_sheets(self):
        datetime_str = datetime.now().strftime("%d-%m-%y %Ih.%Mm.%Ss%p")
        db_connection = settings.DATABASES.get('default')['NAME']
        html_text = f'<h2><a href="https://github.com/hitengajjar/django-excel-transformer"><em>django-excel' \
                    f'-transformer</em></a> Report {datetime_str};</h2><p>Level of Details: {self.options.lod}</p>' \
                    f'<p>Excel file: {self.options.xls_file}</p><p>Database: {db_connection}</p>' \
                    f'<p>Command line option: {self.options}</p><p> '

        for sheet_nm in Registry.parser.get_sheet_names(export_sequence=True):
            config = Registry.parser.get_sheet(sheet_nm)
            model_nm = config.dataset.model_name.rsplit('.')[-1]
            importable_sheet = self.import_sheet(sheet_nm, model_nm, config)
            html_text += f'<br></p><hr><h3>{model_nm}</h3><p>Excel tab: {sheet_nm}</p><p>DB Table: ' \
                         f'{nm(importable_sheet.model)}</p><p>'
            html_text += importable_sheet.get_report(int(self.options.lod))
            html_text += '</p>'

        html_file = open(f'{self.options.report_nm}-report_{datetime_str}.html', 'w')
        html_text += f'<hr><p><em>This report is generated by&nbsp;</em>' \
                     f'<a href="https://github.com/hitengajjar/django-excel-transformer">' \
                     f'<em>django-excel-transformer</em></a></p>'
        html_file.write(html_text)
        html_file.close()

    def import_sheet(self, sheet_nm, model_nm, config) -> Union[ImportableSheet, None]:
        """
        Loads and compares the sheet against DB contents
        :param sheet_nm: excel sheetname
        :param model_nm: Django modelname
        :param config: config.xml section relating to modelname
        :return: ImportableSheet
        """
        try:
            self.importablemodels[model_nm] = importable_sheet = ImportableSheet.from_sheetdata(config)
        except KeyError as ke:
            logging.critical(f'Cannot import sheetnm: {sheet_nm}, modelnm: {model_nm}. Exception: {ke}')
            return None
        logging.info(f'Validating sheet [{sheet_nm}]')
        importable_sheet.load_n_compare()
        if self.options.db_update or self.options.db_force_update:
            importable_sheet.update_db(force_update=self.options.db_force_update)
        return importable_sheet
