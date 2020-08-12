import copy
import logging
from enum import Enum
from typing import Union, re
import typing

from box import Box, BoxList
from django.db.models import TextField, CharField, Model

from ..common import nm, Registry, ColumnCompare, Issue, RowResult, getdictvalue
from .validator import Records1
import attr


class Status(Enum):
    XL = 'XL'
    DB = 'DB'
    MISMATCH = 'MISMATCH'
    NO_CHANGE = 'EQUAL'
    PENDING = 'PENDING'  # pending comparison


class FieldType(Enum):
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
    records: Box
    # defaults: dict
    name: str
    config_filters: Box
    model: Model
    config_data: Box
    index_keys: BoxList
    records: Box

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
                  index_keys=index_keys, records=Box(default_box=True))
        return obj

    def load_data(self):
        xl_data = Registry.xlreader.get_xldata(self.name, self.index_keys)
        for idx, record in xl_data.items():
            self.records[idx] = Record(xl_record=record, status=Status.XL)
        return True

    def compare(self, xl_record, db_record):
        """ Compares xl record vs db record.
         Logic:
         1. know xl record field, using parser resolve FKEY inplace of field but also stores the xl special field _originals
         2. compare FKEY values (read from _originals dictionary) with respective model values (Possible FKEY records are DIFFERENT records in xl and DB, then compare against both)
         3. compare all concrete fields AS IS
         """

        mismatches = BoxList()
        if not xl_record:  # lets compare the values
            mismatches.append(Mismatch(field=None, type=None, status=Status.DB))
        else:
            # 1 - xl record fields
            for field, value in xl_record.items():
                references = self.config_data[field].references  # TODO: HG: This can throw key error
                if references:
                    ref_model = ""
                    refs = Box()
                    values = value.split(' - ')
                    for idx, ref in enumerate(references):
                        ref_model = ref[0]
                        ref_field = ref[1]
                        refs[ref_field] = values[idx]
                        # values[idx] needs to be compared with the value in DB

                    # IMP: Ideally we should pass values and search for record but as of now
                    # we have reference fields are same as reference model's index
                    # e.g. ref field ['name - version'] will be defined as ref model's index as well
                    #   hence it is easy to find the ref record from ref model's importable_sheet's
                    try:
                        record = Registry.importer.get_sheet(ref_model).get_record_dict(refs)
                        if record.status == Status.MISMATCH:
                            mismatches.append(Mismatch(field=field, type=type(value), status=Status.MISMATCH, message='referenced record has MISMATCH', extra_info=record))
                    except KeyError:
                        logging.error(
                            f"{self.model}.{field}'s value {value} - record not available in reference model {ref_model}")
                        mismatches.append(Box(field=field, ))
                elif not hasattr(db_record, field):
                    mismatches.append(Mismatch(field=field, type=type(value), status=Status.XL))
                elif getattr(db_record, field) != value:
                    mismatches.append(Mismatch(field=field, type=type(value), status=Status.MISMATCH))

        return mismatches

    def import_data(self):
        """
           Main function that callers should invoke to import XLS data into DB.

           Reads XLS data and updates records in database for the respective table.
           This is generic function which relies on '_get_record()' to provide records
        """

        # 1. Read xls table and keep them inside records[idx].xl_record
        # 3. compare results and keep them inside records.compare_status
        self.load_data()
        dbobjs = self.model.objects.all()
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
                        value = str(getattr(getattr(dbobj, attr), ref_field)) # TODO: Multi-level references in ref_field e.g. version.component.name
                        idx = value if not idx else idx + ' - ' + value
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

    def get_record_dict(self, datadict: Box):
        # check if datadict has index keys if yes then get_record_idx(self, idx) else scan through all records :(
        if not set(self.index_keys) - datadict.keys():
            return self.get_record_idx(self.get_index(datadict))
        else:
            # TODO: See how to improve performance
            for _, record in self.records.items():
                r1 = r2 = None  # r2 only in case of Mismatch
                if record.status in [Status.XL, Status.NO_CHANGE]:
                    r1 = record.xl_record
                elif record.status == Status.DB:
                    r1 = record.db_record
                elif record.status == Status.MISMATCH:
                    r1 = record.xl_record
                    r2 = record.db_record
                match = True
                for key, value in datadict.items():
                    if getattr(r1, key) != value:
                        match = False
                        break
                if match:
                    return record
                elif r2:  # now check r2
                    for key, value in datadict.items():
                        if getattr(r2, key) != value:
                            match = False
                            break
                    if match:
                        return record
            return None

    def create_record(self, datadict):
        """ Creates or Updates record """
        if not datadict:
            raise ValueError("Missing necessary data for creating object")

        filter = Box()
        for field in self.index_keys:
            filter[field] = datadict[field]
        # TODO: HG: Need to fetch KEY_ID for M2M and FKEY attributes
        self.model.update_or_create(filter, datadict)  # We always expect 1 record per filter

    # def get_record1(self, datadict, ref_check=True) -> Union[object, None]:
    #     """ Provides DB record either cached or using '_alloc_get_db_object()'
    #     :param datadict: should be values with which DB record should be created
    #     :param ref_check: specifies if get_record() should only do reference check. In future,use it to create default object
    #            if record doesn't exists in DB.
    #     :return: None if record not found and ref_check=True else db object
    #     """
    #     logging.debug("Table [%s], with datadict [%s]" % (nm(self._model), datadict))
    #     if not datadict:
    #         raise Exception("[datadict] missing for table [%s]" % (nm(self._model)))
    #
    #     index = self._xl_index_key(datadict)
    #
    #     if index in self.records.db:
    #         logging.debug("Found cached entry for table [%s], with index [%s]" % (nm(self._model), index))
    #         return self.records.db[index]
    #     else:
    #         logging.debug("No cached entry, getting from DB for table [%s], "
    #                       "with index [%s]" % (nm(self._model), index))
    #         obj = self._alloc_get_dbobject(datadict=datadict,  # if ref_check else self._defaults
    #                                        ref_check=ref_check)
    #         if obj:
    #             self.records.db[self._db_index_key(obj)] = obj
    #             # HG: Possibility is less we will come here and still get a DB record.
    #             # because as per current logic, we would already have fetched DB records beforehand
    #         return obj


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

    def import_sheets(self, options):
        for sheet_nm in Registry.parser.get_sheet_names(export_sequence=True):
            config = Registry.parser.get_sheet(sheet_nm)
            model_name = config.dataset.model_name.rsplit('.')[-1]
            self.importablemodels[model_name] = ImportableSheet.from_sheetdata(config)
            self.importablemodels[model_name].import_data()

            logging.info(f'Validating sheet [{sheet_nm}]')
