import copy
import logging
import os
import re
import traceback
from itertools import chain
import builtins
from box import Box

from ..common import get_attr_from_dict, lower, get_ref_model_fields, get_model_col, val
#
# try:
#     from yaml import CLoader as Loader, CDumper as Dumper
# except ImportError:
#     from yaml import Loader, Dumper

from collections import namedtuple
#
# def ordered_load(stream, Loader=yaml.Loader, object_pairs_hook=OrderedDict):
#     'Inspired from https://stackoverflow.com/a/21912744/2133129'
#
#     class OrderedLoader(Loader):
#         pass
#
#     def construct_mapping(loader, node):
#         loader.flatten_mapping(node)
#         return object_pairs_hook(loader.construct_pairs(node))
#
#     OrderedLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
#     return yaml.load(stream, OrderedLoader)
#

def get_defaults(defaults):
    f = Box(default_box=True)
    if 'formatting' in defaults:
        config_f = defaults.formatting

        # Sheet level
        f.read_only = val(config_f.read_only, False)
        f.tab_color = "D9D9D9"

        # Table level
        f.table_style.name = val(config_f.read_only, 'TableStyleMedium')
        f.table_style.show_first_column = val(config_f.table_style.show_first_column, False)
        f.table_style.show_last_column = val(config_f.table_style.show_last_column, False)
        f.table_style.show_row_stripes = val(config_f.table_style.show_row_stripes, True)
        f.table_style.show_column_stripes = val(config_f.table_style.show_column_stripes, True)
        # Column level
        f.data.chars_wrap = val(config_f.data.chars_wrap, 20)
        f.data.comment.text = val(config_f.data.comment.text, '')
        f.data.comment.author = val(config_f.data.comment.author, 'admin@github.com')
        f.data.comment.height_len = val(config_f.data.comment.height_len, 110)
        f.data.comment.width_len = val(config_f.data.comment.width_len, 230)
    default = Box(default_box=True)
    default.formatting = f
    return default

Reference = namedtuple('Reference', ['model', 'field'])
ColFormatting = namedtuple('ColFormatting', ['comment', 'chars_wrap'])
# c = ColFormatting(comment=Box(text='comment', author='author', height_len=100, width_len=230), chars_wrap=20)
Column = namedtuple('Column', ['name', 'formatting', 'references'])
# c = Column(name='dev_orm', formatting=ColFormatting, references=OrderedDict(component=dict(model='Component', field='component')))
Sheet = namedtuple('Sheet', ['name', 'model', 'index_key', 'formatting', 'filters', 'columns'])
# s = Sheet('sheet_nm', dict(read_only=True), dict(ascsort=['component', 'order'], latest=['order']), [Column(...), Column(...)])

class Mapper(object):
    def __init__(self, file_name):
        if not os.path.isfile(file_name):
            raise FileNotFoundError("[%s]" % (file_name))
        stream = builtins.open(file_name, "r").read()
        self._file_name = file_name
        _c = Box.from_yaml(stream, default_box=True)
        _c._box_config['default_box'] = True
        _c.__name__ = 'mapper.yml'
        self._val_status = False
        self.datasets = lower(get_attr_from_dict(_c, 'datasets'))
        self.sheets = {i.sheet_name: i for i in lower(get_attr_from_dict(_c, 'sheets'))}
        self.filters = _c.filters
        self.defaults = get_defaults(_c.defaults)

        errs = self.parse()
        if errs:
            raise Exception('Errors in %s, %s' % (file_name, *dict(errors=errs)))
        self._val_status = True
        self.get_sheet('CompVersion_wo_latest')

    def parse(self):
        """
        Links sheets with datasets and eventually to respective Django model.
        returns list of errors. If empty then no errors
        """

        # TODO: HG: For better error reporting YAML line numbers are useful. Consider https://stackoverflow.com/questions/13319067/parsing-yaml-return-with-line-number

        errs = Box(default_box=True)
        def missing_entries_frm_list(lst: list, entries: list):
            return None if not entries else entries if not lst else list(set(entries) - set(lst))

        def error(label, field, msg, **entries):
            """
            label - can be any thing like sheet_name, file_name, or any random string
            field - field referenced within sheet
            msg - printable message
            entries - additional name-value pairs
            """
            nonlocal errs
            vals = val(errs[label], [])
            vals.append(Box(default_box=True, sheet_name=label, field=field, msg=msg, **entries))
            errs[label] = vals

        def _get_tbl_formatting(ow):
            """default is considered if overwrite doesn't have value"""
            default = self.defaults.formatting
            if not ow:
                formatting = default
            else:
                formatting = Box(default_box=True)

                formatting.read_only = ow.read_only if ow.read_only else default.read_only
                formatting.tab_color = ow.tab_color if ow.tab_color else default.tab_color

                formatting.table_style.name = ow.table_style.name if ow.table_style.name else default.table_style.name
                formatting.table_style.show_first_column = ow.table_style.show_first_column if ow.table_style.show_first_column else default.table_style.show_first_column
                formatting.table_style.show_last_column = ow.table_style.show_last_column if ow.table_style.show_last_column else default.table_style.show_last_column
                formatting.table_style.show_row_stripes = ow.table_style.show_row_stripes if ow.table_style.show_row_stripes else default.table_style.show_row_stripes
                formatting.table_style.show_column_stripes = ow.table_style.show_column_stripes if ow.table_style.show_column_stripes else default.table_style.show_column_stripes

            return formatting

        def _get_col_formatting(field, sheet_formatting) -> Box(chars_wrap=20,comment=None):
            """returns formatting for field if exists else None"""
            default = self.defaults.formatting.data
            col_format = Box(default_box=True, chars_wrap=default.chars_wrap)
            # cols = list(chain(*[cols for cols in sheet_formatting.data]))

            for data_cols in sheet_formatting.data:
                for col in data_cols.columns:
                    if re.findall('^' + col, field):
                        if data_cols.chars_wrap:
                            col_format.chars_wrap = data_cols.chars_wrap
                        if data_cols.comment:
                            col_format.comment.text = data_cols.comment.text if data_cols.comment.text else default.comment.text
                            col_format.comment.author = data_cols.comment.author if data_cols.comment.author else default.comment.author
                            col_format.comment.height_len = data_cols.comment.height_len if data_cols.comment.height_len else default.comment.height_len
                            col_format.comment.width_len = data_cols.comment.width_len if data_cols.comment.width_len else default.comment.width_len
                        # we don't break since we allow overwriting - so same field can have formatting multiple times once with * and then explicit value

            return col_format  # nothing found, return default

        def _parse_dataset(ds, table_name, sheet_name, ds_field) -> Box:
            (model, model_fields) = get_model_col(table_name)
            yml_cols = yml_idx_cols = yml_ref = []
            if not model:
                error(sheet_name, '%s.table_name' % ds_field, '%s is missing' % table_name)
            else:
                try:
                    (yml_idx_cols, yml_cols, yml_ref) = self.get_dataset_data(ds)
                except Exception as e:
                    if isinstance(e, KeyError):
                        error(sheet_name, '%s.data' % ds_field, '%s is missing' % e)
                    else:
                        raise e

                if set(yml_idx_cols) - set(yml_cols) and \
                        (set(yml_idx_cols) - set(
                            [k for col in yml_cols for k in model_fields.keys() if
                             col == '*' or re.findall('^' + col, k)])):
                    error(sheet_name, '%s.data.index_key' % ds_field,
                          'index columns [%s] isn\'t defined in %s.data[].columns' % (
                              set(yml_idx_cols) - set(yml_cols), ds_field))

                data = ds.data
                ds.data = {}
                for idx, datalist in enumerate(data):
                    if 'columns' not in datalist:
                        error(sheet_name, '%s.data[%d]' % (ds_field, idx),
                              '%s.data[%d].columns field isn\'t defined in config file' % (ds_field, idx))
                    else:
                        columns = datalist['columns']
                        references = datalist['references'] if 'references' in datalist else []
                        for col in columns:
                            fields = [k for k in model_fields.keys() if col == '*' or re.findall('^' + col, k)]
                            if not fields:
                                error(sheet_name, '%s.data[%d].columns[%s]' % (ds_field, idx, col),
                                      'field [%s] isn\'t defined in table [%s]' % (f, table_name))
                            else:
                                ds.model = model
                                if col == '*' and 'table_names' in ds:
                                    del ds.table_names
                                    ds.table_name = model.__module__ + "." + model._meta.model_name
                                for f in fields:
                                    if f in ds.data:  # same field may appear multiple times due to support of '*', 'fieldpart_*' and explicit field
                                        # change field order.
                                        prev_obj = ds.data.pop(f)
                                        ds.data[f] = prev_obj  # changing field order
                                    else:
                                        ds.data[f] = Box(default_box=True, references=None)
                                    for ref in references:  # lets link the references if exists
                                        (ref_model, ref_field) = get_ref_model_fields(table_name, f, ref)
                                        if not (ref_model or ref_field):
                                            if not (col == '*' or col[-1:] == '*'):
                                                error(sheet_name, '%s.data[%d].columns[%s]' % (ds_field, idx, col),
                                                  'invalid reference [%s] for field [%s]' % (ref, f))
                                        else:
                                            ds.data[f].references = [] if not ds.data[f].references else ds.data[
                                                f].references
                                            ds.data[f].references.append((ref_model, ref_field))
            return ds

        field_types = Box(chars_wrap=int, text=str, author=str, height_len=int, width_len=int,
                          name=str, show_first_column=bool, show_last_column=bool, show_row_stripes=bool,
                          show_column_stripes=bool, read_only=bool, columns=list, references=list, default_box=True)

        required_fields = Box(sheets=Box(sheet_name=str, dataset=object, default_box=True),
                              filters=Box(column=str, filter=str),
                              datasets=Box(index_key=str, data=object, default_box=True)
                                       + Box({'data.columns': str, 'data.references': str}),
                              formatting=Box(default_box=True),
                              default_box=True)
        supported_fields = Box(sheets=required_fields.sheets + Box(views=str, formatting=object, default_box=True),
                               filters=required_fields.datasets + Box(sort=str, default_box=True),
                               datasets=required_fields.datasets + Box({'data.references': str, 'table_name': str, 'table_names': str}),
                               formatting=required_fields.formatting
                                          + Box({'read_only': str, 'table_style': object,
                                                 'table_style.name': str, 'table_style.show_first_column': bool,
                                                 'table_style.show_last_column': bool,
                                                 'table_style.show_row_stripes': bool,
                                                 'table_style.show_column_stripes': bool, 'data': object,
                                                 'data.chars_wrap': int, 'data.comment': object,
                                                 'data.comment.text': str, 'data.comment.author': str,
                                                 'data.comment.height_len': int, 'data.comment.width_len': int}))

        # TODO: HG: Used supported_fields and remove usage of field_types.

        def validate_type(label, field, value, parent_fields):
            """Validates datatypes against field_types using recursion"""
            nonlocal field_types
            if field is None:
                error(label, '', 'None field in parent %s' % parent_fields)
                return

            fqfn = '%s.%s' % (parent_fields, field)
            if field in field_types and not isinstance(value, field_types[field]):
                error(label, fqfn,
                      'Unsupported type. Expected %s, but received %s' % (field_types[field], type(value)))
            elif isinstance(value, dict):
                for k, v in value.items():
                    validate_type(label, k, v, fqfn)
            elif isinstance(value, list):  # TODO: HG: Will not work for formatting.data[n].columns
                for f in value:
                    validate_type(label, '', f, fqfn)
            elif field not in field_types:  # TODO: HG: use supported_fields here. # Challenge with lists -- need better logic for them
                logging.debug('field %s not in field_types in sheet [%s]' % (fqfn, label))

        def validate_views(sheet_view):
            missing_views = missing_entries_frm_list(self.filters.keys(), sheet_view)
            return missing_views

        # Validate defaults
        if self.defaults:
            validate_type('mapper.yml', 'defaults', self.defaults, 'mapper')

        # Validate sheets along with referenced datasets
        sheet_names = [k for k in self.sheets.keys()]
        for idx, sheet_name in enumerate(sheet_names):
            try:
                base_field = 'mapper.sheets[%d]' % idx
                sheet = self.sheets[sheet_name]

                if 'views' in sheet:  # Validate views (filters)
                    missing_views = validate_views(sheet.views)
                    if missing_views: error(sheet_name, '%s.view' % base_field, 'missing views. check mapper.filters',
                                            views=missing_views)

                # Validate dataset existence
                if not sheet.dataset or sheet.dataset not in self.datasets:
                    error(sheet_name, '%s.dataset' % base_field, 'missing dataset. check mapper.datasets',
                          dataset=sheet.dataset if 'dataset' in sheet else "")
                else:  # Validate dataset entry now
                    # TODO: HG: Need to use Box comparison
                    ds = self.datasets[sheet.dataset]
                    ds_field = "%s.dataset.%s" % (base_field, sheet.dataset)

                    validate_type(label=sheet_name, field=sheet.dataset, value=ds, parent_fields='mapper.datasets')
                    if '*' == sheet_name and 'table_names' in ds:
                        # special case
                        star_sheet_props = self.sheets.pop('*')
                        for table_name in ds.table_names:
                            table_name = table_name.rsplit('.', 1)[-1:][0].lower()
                            sheet = copy.deepcopy(star_sheet_props)
                            sheet.sheet_name = table_name
                            sheet.dataset = _parse_dataset(ds=copy.deepcopy(ds), table_name=table_name,
                                                              sheet_name=table_name, ds_field=ds_field)
                            self.sheets[table_name] = sheet
                    elif 'table_name' in ds:
                        table_name = ds.table_name.rsplit('.', 1)[-1:][0].lower()
                        sheet_name = table_name if '*' == sheet_name else sheet_name
                        sheet.dataset = _parse_dataset(ds=copy.deepcopy(ds), table_name=table_name, sheet_name=sheet_name,
                                                             ds_field=ds_field)
                    else:
                        error(sheet_name, '%s' % ds_field, 'missing \'table_name\' entry. Check mapper.datasets. '
                              'Note: \'table_names\' only supported with sheet_name \'*\'')

                    datakeys = [k for k in sheet.dataset.data.keys()]
                    sheet_formatting = sheet.formatting.copy()
                    del sheet.formatting.data
                    for f in datakeys:
                        sheet.dataset.data[f].formatting = _get_col_formatting(f, sheet_formatting)

                # Validate and update formatting field types
                validate_type(sheet_name, 'formatting', sheet.formatting, 'mapper.sheets')
                sheet.formatting = _get_tbl_formatting(sheet.formatting)

            except Exception as e:
                logging.error('Sheet [%s], exception: [%s]' % (sheet_name, e))
                print(traceback.format_exc())

        return errs
        # TODO: Test cases -
        #   * missing filters -- (a) referenced -- error case, (b) none referenced in sheets
        #   * missing datasets --- (a) referenced in sheets -- error case
        #   * undefined formatting fields -- error case
        #   * 'index' fields
        #       - provide entry that doesn't exists in model
        #       - entry that exists in model but not defined in mapper columns field.
        #   * invalid formatting fields
        #   * columns -
        #       - configure field more than 1 times using either by defining it part of 'fieldpart_*', '*', or explicitly configure for 2 times.
        #           * latest configuration should take effect.
        #   *

    def get_dataset_data(self, ds) -> tuple():
        """
        returns tuple (index_columns_list, [tuple(arr_idx, column)], [tuple(arr_idx, [references])])
        """
        # yml_cols = [(idx, col) for idx, datalist in enumerate(ds.data) for col in datalist['columns']]
        yml_cols = [col for datalist in ds.data for col in datalist['columns']]
        yml_ref = [(idx, ref) for idx, datalist in enumerate(ds.data) if 'references' in datalist for ref in
                   datalist['references']]
        yml_idx = ds.index_key

        return yml_idx, yml_cols, yml_ref

    def get_column_names(self, model_name: str):
        """
        Resolves wildcard columns to appropriate model field name and returns full list of fields in order as defined in yml
        """

        if model_name.strip().lower() not in self.datasets:
            raise Exception('%s missing in datasets' % model_name)
        if self._val_status == False:
            raise Exception('Ensure %s is validated' % self._file_name)
        ds = self.datasets[model_name]
        (model, model_fields) = get_model_col(ds.table_name)
        (yml_idx, yml_cols, yml_ref) = self.get_dataset_data(ds)
        fields = []
        for col in yml_cols:
            if col == '*':
                fields += [f.name for f in model_fields]
            elif col[-1:] == '*':
                fields += [f.name for f in model_fields if re.findall('^' + col.replace('*', '.*'), f.name)]
            else:
                fields.append(col)
        return fields

    def get_sheets(self) -> list:
        """ Provides list of sheets """
        if not self._val_status:
            raise Exception('Ensure %s is validated' % self._file_name)
        return self.sheets.keys()


    def get_sheet(self, sheet_nm: str) -> (Sheet, None):
        """Sheet object if sheet_nm exists else None"""
        if not self._val_status:
            raise Exception('Ensure %s is validated' % self._file_name)

        # We have defined below types earlier in this file
        # Reference = namedtuple('Reference', ['model', 'field'])
        # Column = namedtuple('Column', ['name', 'formatting', 'references'])
        # Sheet = namedtuple('Sheet', ['name', 'formatting', 'filters', 'columns'])
        sheet = None
        if sheet_nm in self.sheets and 'dataset' in self.sheets[sheet_nm]:
            s = self.sheets[sheet_nm]
            ds = s.dataset
            cols = []
            for nm, item in ds.data.items():
                references = [Reference(model=ref[0], field=ref[1]) for ref in item.references] if item.references else []
                cols.append(Column(name=nm, formatting=item.formatting, references=references))
            sheet = Sheet(name=sheet_nm,
                          model=ds.model,
                          index_key=ds.index_key,
                          formatting=s.formatting,
                          filters=s.filters,
                          columns=cols)
        return sheet
