import builtins
import copy
import logging
import os
import re
import traceback
from itertools import chain
from box import Box, BoxList

from .common import get_attr_from_dict, lower, get_model_fields, val, get_model, getdictvalue, get_references


## Documentation part
# a. all str keys in dictionary are stored in lowercase()
# b. avoid using dictionary key for business purpose. have additional key-value within key as its value.
# c. We don't have simple key->simple_value_type pairs we always have key->dict pairs at first level
# d. second level of dict can have key->simple_value_type pairs
# e. Apply this rule to existing code -- we still have fields as key used AS-IS and not converted.

def get_defaults(defaults):
    f = Box(default_box=True, read_only=False)
    config_f = None
    if 'formatting' in defaults:
        config_f = defaults.formatting

    # Sheet level
    f.read_only = getdictvalue(config_f, 'read_only', False)
    f.tab_color = "D9D9D9"
    f.position = config_f.get('position', -1)

    # Table level
    f.table_style.name = getdictvalue(config_f.table_style, 'name', 'TableStyleMedium2')
    # f.table_style.show_first_column = defval_dict(config_f.table_style, 'show_first_column', False)
    f.table_style.show_last_column = getdictvalue(config_f.table_style, 'show_last_column', False)
    f.table_style.show_row_stripes = getdictvalue(config_f.table_style, 'show_row_stripes', True)
    # f.table_style.show_column_stripes = defval_dict(config_f.table_style, 'show_column_stripes', True)

    # Column level
    # col_formatting = Box(default_box=True)
    data = BoxList()
    if not getdictvalue(config_f, 'data', None):
        # for column_config in defval_dict(config_f, 'data', []):
        #     for c in column_config.attributes:
        #         col_formatting[c] = _get_setting(column_config)
        col_formatting = _get_col_setting(None)
        col_formatting['attributes'] = "['*']"
        data.append(col_formatting)
    else:
        data = config_f.data
    f.data = data
    defaults._box_config['default_box'] = True
    defaults.formatting = f
    return defaults


def _get_col_setting(datadict, is_comment: bool = False, excel_dv: bool = False):
    """
    Updates col_format object by fetching required column formatting values available in datadict :param datadict:
    dictionary with column formatting data. If None then return default with attr '*' if available else system
    generated default
    :param is_comment: provide default is_comment object if doesn't exist in datadict.
    :param excel_dv: Excel data validation - applies cross references.
    :return: col_format: object to update with fields column formatting fields available in datadict
    """
    col_format = Box(default_box=True, chars_wrap=10, read_only=False, dv=excel_dv)
    def_comment = Box(text='', author='admin@example.com', height_len=110, width_len=230)
    if datadict and 'chars_wrap' in datadict:
        col_format.chars_wrap = datadict.chars_wrap
    if datadict and 'read_only' in datadict:
        col_format.read_only = datadict.read_only
    if (datadict and 'comment' in datadict) or is_comment:
        comment = getdictvalue(datadict, 'comment', def_comment)
        col_format.comment.text = comment.get('text', def_comment.text)
        col_format.comment.author = comment.get('author', def_comment.author)
        col_format.comment.height_len = comment.get('height_len', def_comment.height_len)
        col_format.comment.width_len = comment.get('width_len', def_comment.width_len)
    return col_format


class Parser(object):
    def __init__(self, file_name):
        """
        :str file_name: mapper file e.g. config.yml
        """
        self.parsed_sheets = Box()
        if not os.path.isfile(file_name):
            raise FileNotFoundError(f'[{file_name}]')
        stream = builtins.open(file_name, "r").read()
        self._file_name = file_name
        _c = Box.from_yaml(stream, default_box=True)
        _c._box_config['default_box'] = True
        _c.__name__ = 'config.yml'
        self._status = False
        self._datasets = lower(get_attr_from_dict(_c, 'datasets'))
        self._sheets = {i.sheet_name: i for i in get_attr_from_dict(_c, 'sheets')}
        self._filters = _c.filters
        self.defaults = get_defaults(_c.defaults)
        self._graph = Box()
        self._errors = Box(default_box=True)

    def _get_tbl_formatting(self, ow):
        """default is considered if overwrite doesn't have value"""
        default = self.defaults.formatting
        if not ow:
            formatting = default
        else:
            formatting = Box(default_box=True)
            formatting.read_only = getdictvalue(ow, 'read_only', default.read_only)
            formatting.position = getdictvalue(ow, 'position', default.position)
            formatting.tab_color = getdictvalue(ow, 'tab_color', default.tab_color)
            formatting.table_style.name = getdictvalue(ow.table_style, 'name', default.table_style.name)
            # formatting.table_style.show_first_column = defval_dict(ow.table_style, 'show_first_column', default.table_style.show_first_column)
            formatting.table_style.show_last_column = getdictvalue(ow.table_style, 'show_last_column',
                                                                   default.table_style.show_last_column)
            formatting.table_style.show_row_stripes = getdictvalue(ow.table_style, 'show_row_stripes',
                                                                   default.table_style.show_row_stripes)
            # if 'data' in ow:
            #     formatting.data = ow.data
            # formatting.table_style.show_column_stripes = defval_dict(ow.table_style, 'show_column_stripes', default.table_style.show_column_stripes)

        return formatting

    def _get_col_formatting(self, attr, datadict: Box, is_comment: bool = False, excel_dv: bool = False) -> Box:
        """
        Returns the column formatting. Special case for 'is_comment = True' - is_comment will be provided
        :param attr: column/field for which formatting information is required
        :param datadict: dictionary with column formatting data
        :param is_comment: include comment if available in default structure
        :param excel_dv: Excel data validation - applies cross references.
        :return:
        """

        # cols = list(chain(*[cols for cols in sheet_formatting.data]))

        def _col_settings(datadict):
            """
            Returns default column setting if available in config.yml
            :param datadict: dictionary with column formatting data
            :return: None if no config for column else Box() with configured settings
            """
            for idx, entry in enumerate(datadict):
                if 'attributes' not in entry:
                    logging.error(f"For attr '{attr}', 'column' key missing inside '{entry}'. Dictionary is '{datadict}'")
                    return _get_col_setting(None, is_comment=is_comment, excel_dv=excel_dv)
                else:
                    if [c for c in entry.attributes if c == '*' or re.findall('^' + c, attr)]:
                        return _get_col_setting(datadict[idx], is_comment, excel_dv=excel_dv)
            return None

        col_format = Box(default_box=True, chars_wrap=10, read_only=False)
        tmp = _col_settings(self.defaults.formatting.data)
        if tmp:
            if 'comment' in tmp and not is_comment:
                del tmp.comment
            col_format = tmp

        tmp = _col_settings(datadict)  # Override if column settings are defined in the `sheets`
        if tmp:
            col_format = tmp

        return col_format

    def parse(self) -> Box:
        """
        Links sheets with datasets and eventually to respective Django model.
        returns list of errors. If empty then no errors
        """

        # TODO: HG: For better error reporting YAML line numbers are useful. Consider
        #  https://stackoverflow.com/questions/13319067/parsing-yaml-return-with-line-number
        # if self._status:  # we have already completed parsing.
        #     return self._errors
        #
        def error(label, field, msg, **entries):
            """
            label - can be any thing like name, file_name, or any random string
            attr - attr referenced within sheet
            msg - printable message
            entries - additional name-value pairs
            """
            vals = getdictvalue(self._errors, label, [])
            vals.append(Box(default_box=True, sheet_name=label, field=field, msg=msg, **entries))
            self._errors[label] = vals

        def _parse_dataset(dataset, model_name, sheet_name, ds_field) -> Box:
            # TODO: HG: Don't do inplace replace. Create separate copy of sheets, datasets, filters, default

            def get_idx_col_refs(ds):
                """
                returns tuple (index_columns_list, [tuple(arr_idx, column)], [tuple(arr_idx, [references])])
                """
                # yml_cols = [(idx, attr) for idx, datalist in enumerate(ds.data) for attr in datalist['attributes']]
                yml_cols = [attr for datalist in ds.data for attr in datalist['attributes']]
                yml_ref = [(idx, ref) for idx, datalist in enumerate(ds.data) if 'references' in datalist for ref in
                           datalist['references']]
                yml_idx = ds.index_key

                return yml_idx, yml_cols, yml_ref

            logging.debug(f'  Processing model: [{model_name}]')
            model = get_model(model_name)
            model_fields = get_model_fields(model)
            yml_cols = yml_idx_cols = yml_ref = []
            if not model:
                error(sheet_name, f'{ds_field}.model_name', f'{model_name} is missing')
            else:
                try:
                    (yml_idx_cols, yml_cols, yml_ref) = get_idx_col_refs(dataset)
                except Exception as e:
                    if isinstance(e, KeyError):
                        error(sheet_name, f'{ds_field}.data', f'[{e}] is missing')
                    else:
                        raise e

                if set(yml_idx_cols) - set(yml_cols) \
                        and (set(yml_idx_cols) - set(
                    [k for attr in yml_cols for k in model_fields.keys() if
                     attr == '*' or re.findall('^' + attr, k)])):
                    error(sheet_name, f'{ds_field}.data.index_key',
                          f'index attributes [{set(yml_idx_cols) - set(yml_cols)}] isnt defined in {ds_field}.data[].attributes')

                data = dataset.data
                dataset.data = {}
                graph_edges = getdictvalue(dataset, 'dependent_models', BoxList())
                for idx, datalist in enumerate(data):
                    if 'attributes' not in datalist:
                        error(sheet_name, f'{ds_field}.data[{idx}]',
                              f'{ds_field}.data[{idx}].attributes field isnt defined in config file')
                        continue

                    attributes = datalist['attributes']
                    references = getdictvalue(datalist, 'references', [])
                    for attr in attributes:
                        logging.debug(f'     attribute [{attr}]')
                        fields = [k for k in model_fields.keys() if attr == '*' or re.findall('^' + attr, k)]
                        if not fields:
                            error(sheet_name, f'{ds_field}.data[{idx}].attributes[{attr}]',
                                  f'No fields defined for  model [{model_name}]')
                            continue
                        dataset.model = model
                        if attr == '*' and 'model_names' in dataset:
                            del dataset.model_names
                            dataset.model_name = model.__module__ + "." + model._meta.model_name
                        for f in fields:
                            if f in dataset.data:
                                # Note: same field may appear multiple times due to support of '*',
                                # 'fieldpart_*' and explicit field
                                # change field order.
                                prev_obj = dataset.data.pop(f)
                                dataset.data[f] = prev_obj  # changing field order
                            else:
                                dataset.data[f] = Box(default_box=True, references=None)

                            try:
                                dataset.data[f].references = get_references(model_name, f, references)
                                graph_edges.extend([ref_model
                                                    for (ref_model, _) in dataset.data[f].references
                                                    if ref_model not in graph_edges])
                            except AttributeError as ae:
                                if not (attr == '*' or attr[-1:] == '*'):
                                    error(sheet_name, f'{ds_field}.data[{idx}].attributes[{attr}]', f'{ae}')
                                    continue

                dataset.dependent_models = graph_edges  # Irrespective of ref_model exist or not, we create entry

            return dataset

        field_types = Box(chars_wrap=int, text=str, author=str, height_len=int, width_len=int,
                          name=str, show_first_column=bool, show_last_column=bool, show_row_stripes=bool,
                          show_column_stripes=bool, read_only=bool, attributes=list, references=list, default_box=True)

        # TODO: HG: Used supported_fields and remove usage of field_types.
        # required_fields = Box(sheets=Box(sheet_name=str, dataset=object, default_box=True),
        #                       filters=Box(column=str, filter=str),
        #                       datasets=Box(index_key=str, data=object, default_box=True)
        #                                + Box({'data.attributes': str, 'data.references': str}),
        #                       formatting=Box(default_box=True),
        #                       default_box=True)
        # supported_fields = Box(sheets=required_fields.sheets + Box(views=str, formatting=object, default_box=True),
        #                        filters=required_fields.datasets + Box(sort=str, default_box=True),
        #                        datasets=required_fields.datasets + Box(
        #                            {'data.references': str, 'model_name': str, 'model_names': str}),
        #                        formatting=required_fields.formatting
        #                                   + Box({'read_only': str, 'table_style': object,
        #                                          'table_style.name': str, 'table_style.show_first_column': bool,
        #                                          'table_style.show_last_column': bool,
        #                                          'table_style.show_row_stripes': bool,
        #                                          'table_style.show_column_stripes': bool, 'data': object,
        #                                          'data.chars_wrap': int, 'data.comment': object,
        #                                          'data.comment.text': str, 'data.comment.author': str,
        #                                          'data.comment.height_len': int, 'data.comment.width_len': int}))

        def _validate_type(label, field, value, parent_fields):
            """Validates datatypes against field_types using recursion"""
            nonlocal field_types
            if field is None:
                error(label, '', f'field is None. parent fields are [{parent_fields}]')
                return

            fqfn = f'{parent_fields}.{field}'
            if field in field_types and not isinstance(value, field_types[field]):
                error(label, fqfn, f'Unsupported type. Expected {field_types[field]}, but received {type(value)}')
            elif isinstance(value, dict):
                for k, v in value.items():
                    _validate_type(label, k, v, fqfn)
            elif isinstance(value, list):  # TODO: HG: Will not work for cf.data[n].attributes so fix it
                for f in value:
                    _validate_type(label, '', f, fqfn)
            elif field not in field_types:  # TODO: HG: use supported_fields here.
                logging.debug(f'field [{fqfn}] not in field_types for sheet [{label}]')

        # Validate defaults
        if self.defaults:
            _validate_type('config.yml', 'defaults', self.defaults, 'mapper')

        sheet_model_map = Box(default_box=True, default_box_attr=BoxList)  # model_name -> name

        # Validate sheets along with referenced datasets
        for sheet_name, sheet in self._sheets.items():
            logging.debug(f'Processing sheet [{sheet_name}]')
            try:
                base_field = f'mapper.sheets[{sheet_name}]'

                if 'filter' in sheet:  # Validate filter
                    if sheet.filter not in self._filters.keys():
                        error(sheet_name, f'{base_field}.filter', 'missing filter. check mapper.filters',
                              filter=sheet.filter)
                    else:
                        sheet.filters = self._filters[sheet.filter]
                        del sheet.filter

                # Validate dataset existence
                if not sheet.dataset or sheet.dataset not in self._datasets:
                    error(sheet_name, f'{base_field}.dataset',
                          f'missing dataset. check [mapper.datasets] for sheet {base_field}',
                          dataset=sheet.get('dataset', ''))
                else:  # and now Validate dataset entry
                    logging.debug(f'Sheet with dataset [{sheet.dataset}]')
                    ds = self._datasets[sheet.dataset]
                    ds_field = f'{base_field}.dataset.{sheet.dataset}'

                    _validate_type(label=sheet_name, field=sheet.dataset, value=ds, parent_fields='mapper.datasets')

                    models = ds.get('model_names', [ds.model_name])
                    for model_name in models:
                        model_name = model_name.rsplit('.', 1)[-1:][0]
                        dup_sheet = copy.deepcopy(sheet)
                        if '*' == sheet_name:  # Change sheet name only if its '*'
                            dup_sheet.sheet_name = model_name
                        dup_sheet.dataset = _parse_dataset(dataset=copy.deepcopy(ds), model_name=model_name,
                                                           sheet_name=dup_sheet.sheet_name, ds_field=ds_field)
                        self.parsed_sheets[dup_sheet.sheet_name] = dup_sheet

                        # We can have multiple sheets for same model with different filters.
                        sheet_model_map[model_name.lower()].append(dup_sheet.sheet_name)

                        datakeys = [k for k in dup_sheet.dataset.data.keys()]
                        sheet_formatting = dup_sheet.formatting.copy()
                        model_fields = get_model_fields(dup_sheet.dataset.model)
                        for f in datakeys:
                            excel_dv = True if dup_sheet.dataset.data[f].references and model_fields[
                                f].many_to_one else False
                            dup_sheet.dataset.data[f].formatting = self._get_col_formatting(f, sheet_formatting.data,
                                                                                            excel_dv=excel_dv)
                        if 'data' in dup_sheet.formatting.data:
                            del dup_sheet.formatting.data
                        # Validate and update table formatting
                        _validate_type(sheet_name, 'formatting', dup_sheet.formatting, 'mapper.sheets')
                        dup_sheet.formatting = self._get_tbl_formatting(dup_sheet.formatting)

            except Exception as e:
                logging.error(f'Sheet [{sheet_name}], exception: [{e}]')
                print(traceback.format_exc())

        for sheet_name, sheet in self.parsed_sheets.items():  # We have case where model is referred but not exported or imported
            sheet.dependent_sheets = list(
                chain(*[sheet_model_map[dep_model.lower()] for dep_model in sheet.dataset.dependent_models if
                        dep_model.lower() in sheet_model_map]))

        if not self._errors:
            self._status = True
        return self._errors
        # TODO: Test cases -
        #   * missing filters -- (a) referenced -- error case, (b) none referenced in sheets
        #   * missing datasets --- (a) referenced in sheets -- error case
        #   * undefined cf fields -- error case
        #   * 'index' fields
        #       - provide entry that doesn't exists in model
        #       - entry that exists in model but not defined in mapper attributes field.
        #   * invalid cf fields
        #   * attributes -
        #       - configure field more than 1 times using either by defining it part of 'fieldpart_*', '*', or explicitly configure for 2 times.
        #           * latest configuration should take effect.

    def get_sheet_names(self, export_sequence=True) -> list:
        """
        Provides all the sheets. Ordering is dependent on export_sequence flag.
        :param export_sequence: if True then sheets are provided in order that can be easily exported - uses DFS.
                                if False, provides sheet names as they appear in mapper yml configuration file.
        :return: list of sheet names.
        """
        if not export_sequence:
            return list(self.parsed_sheets.keys())
        visited = set()
        graph = self.parsed_sheets.keys()
        dfs_nodes = BoxList()

        def dfs(node):
            nonlocal visited, graph
            if node not in visited:
                visited.add(node)
                dependents = self.parsed_sheets[node].dependent_sheets
                for neighbour in dependents:
                    dfs(neighbour)
                dfs_nodes.append(node)

        while 1:
            starting_node = set(graph) - set(visited)
            if not starting_node:
                break
            dfs(starting_node.pop())

        logging.info(dfs_nodes)
        return dfs_nodes

    def get_sheet(self, sheet_name: str) -> Box:
        """Sheet object if name exists else None"""
        if not self._status:
            raise Exception(f'Ensure {self._file_name} is validated')

        return getdictvalue(self.parsed_sheets, sheet_name, None)
        # TODO: HG: We have an issue to fix when we use filter on sample table and have multiple sheets exported and dependent sheet doesn't know how to link excel validation
        # e.g. compversion_latest and compversion_wo_latest -> use model 'componentversionmodel'
        #       compdependency depends upon model 'componentversionmodel' hence it needs to know which sheet to refer.

    @property
    def status(self):
        return self._status

    @property
    def errors(self):
        return self._errors
