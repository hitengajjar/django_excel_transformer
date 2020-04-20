import builtins
import copy
import logging
import os
import re
import traceback
from collections import namedtuple
from itertools import chain

from box import Box, BoxList

from ..common import get_attr_from_dict, lower, get_ref_model_fields, get_model_col, val

## TODO: HG: Documentation part
# a. all keys in dictionary is stored in lowercase()
# b. avoid using dictionary key for business purpose. have additional key-value within key as its value.
# c. We don't have simple key->simple_value_type pairs we always have key->dict pairs at first level
# d. second level of dict can have key->simple_value_type pairs
# e. Apply this rule to existing code -- we still have fields as key used AS-IS and not converted.

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


# Reference = namedtuple('Reference', ['model', 'field'])
# ColFormatting = namedtuple('ColFormatting', ['comment', 'chars_wrap'])
# # c = ColFormatting(comment=Box(text='comment', author='author', height_len=100, width_len=230), chars_wrap=20)
# Column = namedtuple('Column', ['name', 'formatting', 'references'])
# # c = Column(name='dev_orm', formatting=ColFormatting, references=OrderedDict(component=dict(model='Component',
# # field='component')))
# Sheet = namedtuple('Sheet', ['name', 'model', 'index_key', 'formatting', 'filters', 'columns'])
# s = Sheet('sheet_nm', dict(read_only=True), dict(ascsort=['component', 'order'], latest=['order']), [Column(...),
# Column(...)])

class Mapper(object):
    def __init__(self, file_name):
        """
        :str file_name: mapper file e.g. mapper.yml
        """
        if not os.path.isfile(file_name):
            raise FileNotFoundError("[%s]" % file_name)
        stream = builtins.open(file_name, "r").read()
        self._file_name = file_name
        _c = Box.from_yaml(stream, default_box=True)
        _c._box_config['default_box'] = True
        _c.__name__ = 'mapper.yml'
        self._val_status = False
        self.datasets = lower(get_attr_from_dict(_c, 'datasets'))
        self.sheets = {i.sheet_name.lower(): i for i in lower(get_attr_from_dict(_c, 'sheets'))}
        self.filters = _c.filters
        self.defaults = get_defaults(_c.defaults)
        self._graph = Box()

        errs = self.parse()
        if errs:
            raise Exception('Errors in %s, %s' % (file_name, *dict(errors=errs)))
        self._val_status = True

    def parse(self) -> Box:
        """
        Links sheets with datasets and eventually to respective Django model.
        returns list of errors. If empty then no errors
        """

        # TODO: HG: For better error reporting YAML line numbers are useful. Consider
        #  https://stackoverflow.com/questions/13319067/parsing-yaml-return-with-line-number
        errs = Box(default_box=True)

        if self._val_status:  # we have already completed parsing.
            return errs

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

                formatting.table_style.name = ow.table_style.name \
                    if ow.table_style.name else default.table_style.name
                formatting.table_style.show_first_column = ow.table_style.show_first_column \
                    if ow.table_style.show_first_column else default.table_style.show_first_column
                formatting.table_style.show_last_column = ow.table_style.show_last_column \
                    if ow.table_style.show_last_column else default.table_style.show_last_column
                formatting.table_style.show_row_stripes = ow.table_style.show_row_stripes \
                    if ow.table_style.show_row_stripes else default.table_style.show_row_stripes
                formatting.table_style.show_column_stripes = ow.table_style.show_column_stripes \
                    if ow.table_style.show_column_stripes else default.table_style.show_column_stripes

            return formatting

        def _get_col_formatting(field, data_formatting) -> Box:
            """returns formatting for field if exists else None"""
            default = self.defaults.formatting.data
            col_format = Box(default_box=True, chars_wrap=default.chars_wrap)
            # cols = list(chain(*[cols for cols in sheet_formatting.data]))

            # data_cols: Box(column='col', comment=Box(text='',author='',height_len=1,width_len=1))
            for data_cols in data_formatting:
                if 'columns' in data_cols:
                    for col in data_cols.columns:
                        if re.findall('^' + col, field):
                            if 'chars_wrap' in data_cols:
                                col_format.chars_wrap = data_cols.chars_wrap
                            if 'comment' in data_cols:
                                col_format.comment.text = data_cols.comment.text \
                                    if 'text' in data_cols.comment else default.comment.text
                                col_format.comment.author = data_cols.comment.author \
                                    if 'author' in data_cols.comment else default.comment.author
                                col_format.comment.height_len = data_cols.comment.height_len \
                                    if 'height_len' in data_cols.comment else default.comment.height_len
                                col_format.comment.width_len = data_cols.comment.width_len \
                                    if 'width_len' in data_cols.comment else default.comment.width_len
                        # we don't break since we allow overwriting - so same field can have formatting multiple
                        # times once with * and then explicit value

            return col_format  # nothing found, return default

        def _parse_dataset(ds, model_name, sheet_name, ds_field) -> Box:
            # TODO: HG: Don't do inplace replace. Create separate copy of sheets, datasets, filters, default

            (model, model_fields) = get_model_col(model_name)
            yml_cols = yml_idx_cols = yml_ref = []
            if not model:
                error(sheet_name, '%s.model_name' % ds_field, '%s is missing' % model_name)
            else:
                try:
                    (yml_idx_cols, yml_cols, yml_ref) = self.get_idx_col_refs(ds)
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
                graph_edges = ds.dependent_models if 'dependent_models' in ds else BoxList()
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
                                      'No fields defined for  model [%s]' % model_name)
                            else:
                                ds.model = model
                                if col == '*' and 'model_names' in ds:
                                    del ds.model_names
                                    ds.model_name = model.__module__ + "." + model._meta.model_name
                                for f in fields:
                                    if f in ds.data:  # same field may appear multiple times due to support of '*',
                                        # 'fieldpart_*' and explicit field
                                        # change field order.
                                        prev_obj = ds.data.pop(f)
                                        ds.data[f] = prev_obj  # changing field order
                                    else:
                                        ds.data[f] = Box(default_box=True, references=None)
                                    for ref in references:  # lets link the references if exists
                                        (ref_model, ref_field) = get_ref_model_fields(model_name, f, ref)
                                        if ref_model and ref_model.__name__ not in graph_edges:
                                            graph_edges.append(ref_model.__name__)

                                        if not (ref_model or ref_field):
                                            if not (col == '*' or col[-1:] == '*'):
                                                error(sheet_name, '%s.data[%d].columns[%s]' % (ds_field, idx, col),
                                                      'invalid reference [%s] for field [%s]' % (ref, f))
                                        else:
                                            ds.data[f].references = [] if not ds.data[f].references else ds.data[
                                                f].references
                                            ds.data[f].references.append((ref_model, ref_field))
                ds.dependent_models = graph_edges  # Irrespective of ref_model exist or not, we create entry

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
                               datasets=required_fields.datasets + Box(
                                   {'data.references': str, 'model_name': str, 'model_names': str}),
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

        def _validate_type(label, field, value, parent_fields):
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
                    _validate_type(label, k, v, fqfn)
            elif isinstance(value, list):  # TODO: HG: Will not work for formatting.data[n].columns
                for f in value:
                    _validate_type(label, '', f, fqfn)
            elif field not in field_types:  # TODO: HG: use supported_fields here. # Challenge with lists -- need
                # better logic for them
                logging.debug('field %s not in field_types in sheet [%s]' % (fqfn, label))

        # Validate defaults
        if self.defaults:
            _validate_type('mapper.yml', 'defaults', self.defaults, 'mapper')

        sheet_model_map = Box(default_box=True, default_box_attr=BoxList)  # model_name -> sheet_name

        # Validate sheets along with referenced datasets
        self.parsed_sheets = Box(default_box=True)
        for sheet_name, sheet in self.sheets.items():
            try:
                base_field = 'mapper.sheets[%s]' % sheet_name

                if 'view' in sheet:  # Validate view (filters)
                    if sheet.view not in self.filters.keys():
                        error(sheet_name, '%s.view' % base_field, 'missing view. check mapper.filters',
                              view=sheet.view)
                    else:
                        sheet.filters = self.filters[sheet.view]
                        del sheet.view

                # Validate dataset existence
                if not sheet.dataset or sheet.dataset not in self.datasets:
                    error(sheet_name, '%s.dataset' % base_field, 'missing dataset. check mapper.datasets',
                          dataset=sheet.dataset if 'dataset' in sheet else "")
                else:  # Now Validate dataset entry
                    ds = self.datasets[sheet.dataset]
                    ds_field = "%s.dataset.%s" % (base_field, sheet.dataset)

                    _validate_type(label=sheet_name, field=sheet.dataset, value=ds, parent_fields='mapper.datasets')

                    models = ds.model_names if 'model_names' in ds else [ds.model_name]
                    # tmp_sheet = self.sheets.pop(sheet_name)
                    for model_name in models:
                        model_name = model_name.rsplit('.', 1)[-1:][0]
                        dup_sheet = copy.deepcopy(sheet)
                        if '*' == sheet_name:  # Change sheet name only if its '*'
                            dup_sheet.sheet_name = model_name
                        dup_sheet.dataset = _parse_dataset(ds=copy.deepcopy(ds), model_name=model_name,
                                                       sheet_name=dup_sheet.sheet_name, ds_field=ds_field)
                        self.parsed_sheets[dup_sheet.sheet_name] = dup_sheet

                        sheet_model_map[model_name.lower()].append(dup_sheet.sheet_name)  # We can have multiple sheets for same model with different filters.

                        # if ['model_names', 'model_name'] not in ds:  TODO: HG: check if none of these exists and flag error
                        #     error(sheet_name, '%s' % ds_field,
                        #           'missing \'model_name\' entry. Check mapper.datasets. '
                        #           'Note: \'model_names\' only supported with sheet_name \'*\'')
                        datakeys = [k for k in dup_sheet.dataset.data.keys()]
                        sheet_formatting = dup_sheet.formatting.copy()
                        for f in datakeys:
                            dup_sheet.dataset.data[f].formatting = _get_col_formatting(f, sheet_formatting.data)
                        if 'data' in dup_sheet.formatting.data:
                            del dup_sheet.formatting.data

                # Validate and update formatting field types
                _validate_type(sheet_name, 'formatting', sheet.formatting, 'mapper.sheets')
                sheet.formatting = _get_tbl_formatting(sheet.formatting)
            except Exception as e:
                logging.error('Sheet [%s], exception: [%s]' % (sheet_name, e))
                print(traceback.format_exc())

        for sheet_name, sheet in self.parsed_sheets.items():  # We have case where model is referred but not exported or imported
            sheet.dependent_sheets = list(chain(*[sheet_model_map[dep_model.lower()] for dep_model in sheet.dataset.dependent_models if
                                      dep_model.lower() in sheet_model_map]))

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

    def get_idx_col_refs(self, ds) -> tuple():
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

        if lower(model_name) not in self.datasets:
            raise Exception('%s missing in datasets' % model_name)
        if self._val_status == False:
            raise Exception('Ensure %s is validated' % self._file_name)
        ds = self.datasets[lower(model_name)]
        (model, model_fields) = get_model_col(ds.model_name)
        (yml_idx, yml_cols, yml_ref) = self.get_idx_col_refs(ds)
        fields = []
        for col in yml_cols:
            if col == '*':
                fields += [f.name for f in model_fields]
            elif col[-1:] == '*':
                fields += [f.name for f in model_fields if re.findall('^' + col.replace('*', '.*'), f.name)]
            else:
                fields.append(col)
        return fields
    #
    # def get_sheets(self) -> list:
    #     """ Provides list of sheets """
    #     if not self._val_status:
    #         raise Exception('Ensure %s is validated' % self._file_name)
    #     return self.parsed_sheets.keys()

    def get_sheets(self, export_sequence=True) -> list:
        """
        Provides all the sheets. Ordering is dependent on export_sequence flag.
        :param export_sequence: if True then sheets are provided in order that can be easily exported - uses DFS.
                                if False, provides sheet names as they appear in mapper yml configuration file.
        :return: list of sheets.
        """
        visited = set()
        graph = lower(self.parsed_sheets.keys())
        dfs_nodes = BoxList()

        def dfs(node):
            nonlocal visited, graph
            node = node.lower()
            if node not in visited:
                visited.add(node)
                dependents = lower(self.parsed_sheets[node].dependent_sheets)
                for neighbour in dependents:
                    dfs(neighbour)
                dfs_nodes.append(node)

        while(1):
            starting_node = set(graph) - set(visited)
            if not starting_node:
                break
            dfs(starting_node.pop())

        print(dfs_nodes)
        return dfs_nodes

    def get_sheet(self, sheet_nm: str) -> Box:
        """Sheet object if sheet_nm exists else None"""
        if not self._val_status:
            raise Exception('Ensure %s is validated' % self._file_name)
        return self.parsed_sheets[sheet_nm] if sheet_nm in self.sheets else None
        # TODO: HG: We have an issue to fix when we use filter on sample table and have multiple sheets exported and dependent sheet doesn't know how to link excel validation
        # e.g. compversion_latest and compversion_wo_latest -> use model 'componentversionmodel'
        #       compdependency depends upon model 'componentversionmodel' hence it needs to know which sheet to refer.
