import builtins
import copy
import logging
import os
import re
import traceback
from itertools import chain
from box import Box, BoxList

from .common import get_attr_from_dict, lower, get_model_fields, val, get_model, defval_dict


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
    f.read_only = defval_dict(config_f, 'read_only', False)
    f.tab_color = "D9D9D9"
    f.position = config_f.get('position', -1)

    # Table level
    f.table_style.name = defval_dict(config_f.table_style, 'name', 'TableStyleMedium2')
    # f.table_style.show_first_column = defval_dict(config_f.table_style, 'show_first_column', False)
    f.table_style.show_last_column = defval_dict(config_f.table_style, 'show_last_column', False)
    f.table_style.show_row_stripes = defval_dict(config_f.table_style, 'show_row_stripes', True)
    # f.table_style.show_column_stripes = defval_dict(config_f.table_style, 'show_column_stripes', True)

    # Column level
    # col_formatting = Box(default_box=True)
    data = BoxList()
    if not defval_dict(config_f, 'data', None):
        # for column_config in defval_dict(config_f, 'data', []):
        #     for c in column_config.columns:
        #         col_formatting[c] = _get_setting(column_config)
        col_formatting = _get_col_setting(None)
        col_formatting['columns'] = "['*']"
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
    dictionary with column formatting data. If None then return default with col '*' if available else system
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
        comment = defval_dict(datadict, 'comment', def_comment)
        col_format.comment.text = comment.get('text', def_comment.text)
        col_format.comment.author = comment.get('author', def_comment.author)
        col_format.comment.height_len = comment.get('height_len', def_comment.height_len)
        col_format.comment.width_len = comment.get('width_len', def_comment.width_len)
    return col_format


class Parser(object):
    def __init__(self, file_name):
        """
        :str file_name: mapper file e.g. mapper.yml
        """
        self.parsed_sheets = Box(default_box=True)
        if not os.path.isfile(file_name):
            raise FileNotFoundError("[%s]" % file_name)
        stream = builtins.open(file_name, "r").read()
        self._file_name = file_name
        _c = Box.from_yaml(stream, default_box=True)
        _c._box_config['default_box'] = True
        _c.__name__ = 'mapper.yml'
        self._status = False
        self._datasets = lower(get_attr_from_dict(_c, 'datasets'))
        self._sheets = {i.sheet_name.lower(): i for i in lower(get_attr_from_dict(_c, 'sheets'))}
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
            formatting.read_only = defval_dict(ow, 'read_only', default.read_only)
            formatting.position = defval_dict(ow, 'position', default.position)
            formatting.tab_color = defval_dict(ow, 'tab_color', default.tab_color)
            formatting.table_style.name = defval_dict(ow.table_style, 'name', default.table_style.name)
            # formatting.table_style.show_first_column = defval_dict(ow.table_style, 'show_first_column', default.table_style.show_first_column)
            formatting.table_style.show_last_column = defval_dict(ow.table_style, 'show_last_column',
                                                                  default.table_style.show_last_column)
            formatting.table_style.show_row_stripes = defval_dict(ow.table_style, 'show_row_stripes',
                                                                  default.table_style.show_row_stripes)
            # formatting.table_style.show_column_stripes = defval_dict(ow.table_style, 'show_column_stripes', default.table_style.show_column_stripes)

        return formatting

    def _get_col_formatting(self, col, datadict: Box, is_comment: bool = False, excel_dv: bool = False) -> Box:
        """
        Returns the column formatting. Special case for 'is_comment = True' - is_comment will be provided
        :param col: column/field for which formatting information is required
        :param datadict: dictionary with column formatting data
        :param is_comment: include comment if available in default structure
        :param excel_dv: Excel data validation - applies cross references.
        :return:
        """

        # cols = list(chain(*[cols for cols in sheet_formatting.data]))

        def _col_settings(col, datadict, is_comment: bool = False, excel_dv: bool = False):
            """
            Returns default column setting if available in mapper.yml
            :param column:
            :param datadict: dictionary with column formatting data
            :param is_comment: provide default is_comment object if doesn't exist in datadict.
            :param excel_dv: Excel data validation - applies cross references.
            :return: None if no config for column else Box() with configured settings
            """
            for idx, entry in enumerate(datadict):
                if 'columns' not in entry:
                    logging.error(f"For col '{col}', 'column' key missing inside '{entry}'. Dictionary is '{datadict}'")
                    return _get_col_setting(None, is_comment=is_comment, excel_dv=excel_dv)
                else:
                    if [c for c in entry.columns if c == '*' or re.findall('^' + c, col)]:
                        return _get_col_setting(datadict[idx], is_comment, excel_dv=excel_dv)
            return None

        col_format = Box(default_box=True, chars_wrap=10, read_only=False)
        tmp = _col_settings(col, self.defaults.formatting.data, is_comment, excel_dv)
        if tmp:
            if 'comment' in tmp and not is_comment:
                del tmp.comment
            col_format = tmp

        tmp = _col_settings(col, datadict, is_comment, excel_dv)  # Override if column settings are defined in the
        # `sheets`
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
            col - col referenced within sheet
            msg - printable message
            entries - additional name-value pairs
            """
            vals = defval_dict(self._errors, label, [])
            vals.append(Box(default_box=True, sheet_name=label, field=field, msg=msg, **entries))
            self._errors[label] = vals

        def get_references(model_name, field, references):
            """
            Validates and provides valid reference fields. In case of invalid fields will throw AttributeError. If
            wrong models are referenced then will throw ValueError :param model_name: model name :param col: model
            col :param references: list of reference :return:
            """
            ref_data = []
            model = get_model(model_name)
            fields = get_model_fields(model)
            django_field_nm = [tmp for tmp in fields if lower(field) == lower(tmp)]
            # need exact col name for de-referencing within Django model
            if not django_field_nm:
                raise AttributeError(f'model [{model_name}] doesnt have col [{django_field_nm}]')

            django_field_nm = django_field_nm[0]

            if references and not model._meta.get_field(django_field_nm).is_relation:
                raise AttributeError(
                    f'model [{model_name}], col [{django_field_nm}] isnt a reference col. mapper references: [{references}]')
            elif model._meta.get_field(django_field_nm).is_relation and not references:
                references = ["$model.id"]  # Lets add ref by ourselves, eases export and import

            for ref in references:
                ref_field = ref.rsplit('.', 1)[-1:][0]
                if ref.strip().split('.')[0].strip() == '$model':
                    ref_model = model._meta.get_field(django_field_nm).related_model
                    ref_model_str = ref_model._meta.model_name
                else:
                    # TODO: HG: Ideally we don't need this unless we provide functionality where sheet_column_name is
                    #  different from data_field but in that case too, we need to be able to map column_name to
                    #  field_name which we don't have right now.
                    ref_model_str = ref.rsplit('.', 2)[-2:][0].strip().lower() if len(
                        ref.rsplit('.', 2)[-2:]) > 1 else None
                    ref_model = get_model(ref_model_str)
                    if ref_model != model._meta.get_field(django_field_nm).related_model:
                        raise ValueError(f'Invalid model [{ref_model_str}] '
                                         f'expected [{model._meta.get_field(django_field_nm).related_model}]')
                fields = [tmp for tmp in get_model_fields(ref_model).keys() if
                          lower(ref_field) == lower(
                              tmp)]  # need exact col name for de-referencing within Django model
                if ref_field != 'id' and not fields:
                    raise ValueError(f'Invalid reference_field [{ref_field}] for '
                                     f'col [{django_field_nm}], model [{model_name}]')
                if ref_field != 'id':
                    ref_field = fields[0]
                ref_data.append((ref_model_str, ref_field))
            return ref_data

        def _parse_dataset(dataset, model_name, sheet_name, ds_field) -> Box:
            # TODO: HG: Don't do inplace replace. Create separate copy of sheets, datasets, filters, default

            def get_idx_col_refs(ds):
                """
                returns tuple (index_columns_list, [tuple(arr_idx, column)], [tuple(arr_idx, [references])])
                """
                # yml_cols = [(idx, col) for idx, datalist in enumerate(ds.data) for col in datalist['columns']]
                yml_cols = [col for datalist in ds.data for col in datalist['columns']]
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
                        error(sheet_name, f'{ds_field}.data', f'{e} is missing')
                    else:
                        raise e

                if set(yml_idx_cols) - set(yml_cols) \
                        and (set(yml_idx_cols) - set(
                    [k for col in yml_cols for k in model_fields.keys() if
                     col == '*' or re.findall('^' + col, k)])):
                    error(sheet_name, '%s.data.index_key' % ds_field,
                          f'index columns [{set(yml_idx_cols) - set(yml_cols)}] isn\'t defined '
                          f'in {ds_field}.data[].columns')

                data = dataset.data
                dataset.data = {}
                graph_edges = defval_dict(dataset, 'dependent_models', BoxList())
                for idx, datalist in enumerate(data):
                    if 'columns' not in datalist:
                        error(sheet_name, f'{ds_field}.data[{idx}]',
                              f'{ds_field}.data[{idx}].columns col isn\'t defined in config file')
                        continue

                    columns = datalist['columns']
                    references = defval_dict(datalist, 'references', [])
                    for col in columns:
                        logging.debug(f'     column [{col}]')
                        fields = [k for k in model_fields.keys() if col == '*' or re.findall('^' + col, k)]
                        if not fields:
                            error(sheet_name, f'{ds_field}.data[{idx}].columns[{col}]',
                                  f'No fields defined for  model [{model_name}]')
                            continue
                        dataset.model = model
                        if col == '*' and 'model_names' in dataset:
                            del dataset.model_names
                            dataset.model_name = model.__module__ + "." + model._meta.model_name
                        for f in fields:
                            if f in dataset.data:
                                # Note: same col may appear multiple times due to support of '*',
                                # 'fieldpart_*' and explicit col
                                # change col order.
                                prev_obj = dataset.data.pop(f)
                                dataset.data[f] = prev_obj  # changing col order
                            else:
                                dataset.data[f] = Box(default_box=True, references=None)

                            try:
                                dataset.data[f].references = get_references(model_name, f, references)

                                graph_edges.extend([ref_model
                                                    for (ref_model, _) in dataset.data[f].references
                                                    if ref_model not in graph_edges])
                            except AttributeError as ae:
                                if not (col == '*' or col[-1:] == '*'):
                                    error(sheet_name, f'{ds_field}.data[{idx}].columns[{col}]', f'{ae}')
                                    continue

                dataset.dependent_models = graph_edges  # Irrespective of ref_model exist or not, we create entry

            return dataset

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
                error(label, '', f'None col in parent {parent_fields}')
                return

            fqfn = f'{parent_fields}.{field}'
            if field in field_types and not isinstance(value, field_types[field]):
                error(label, fqfn,
                      f'Unsupported type. Expected {field_types[field]}, but received {type(value)}')
            elif isinstance(value, dict):
                for k, v in value.items():
                    _validate_type(label, k, v, fqfn)
            elif isinstance(value, list):  # TODO: HG: Will not work for cf.data[n].columns
                for f in value:
                    _validate_type(label, '', f, fqfn)
            elif field not in field_types:  # TODO: HG: use supported_fields here. # Challenge with lists -- need
                # better logic for them
                logging.debug(f'col {fqfn} not in field_types in sheet [{label}]')

        # Validate defaults
        if self.defaults:
            _validate_type('mapper.yml', 'defaults', self.defaults, 'mapper')

        sheet_model_map = Box(default_box=True, default_box_attr=BoxList)  # model_name -> name

        # Validate sheets along with referenced datasets
        for sheet_name, sheet in self._sheets.items():
            logging.debug(f'Processing sheet {sheet_name}')
            try:
                base_field = f'mapper.sheets[{sheet_name}]'

                if 'view' in sheet:  # Validate view (filters)
                    if sheet.view not in self._filters.keys():
                        error(sheet_name, f'{base_field}.view', 'missing view. check mapper.filters',
                              view=sheet.view)
                    else:
                        sheet.filters = self._filters[sheet.view]
                        del sheet.view

                # Validate dataset existence
                if not sheet.dataset or sheet.dataset not in self._datasets:
                    error(sheet_name, f'{base_field}.dataset', 'missing dataset. check mapper.datasets',
                          dataset=defval_dict(sheet, 'dataset', ""))
                else:  # Now Validate dataset entry
                    logging.debug(f'Sheet with dataset [{sheet.dataset}]')
                    ds = self._datasets[sheet.dataset]
                    ds_field = f'{base_field}.dataset.{sheet.dataset}'

                    _validate_type(label=sheet_name, field=sheet.dataset, value=ds, parent_fields='mapper.datasets')

                    models = defval_dict(ds, 'model_names', [ds.model_name])
                    # tmp_sheet = self.sheets.pop(name)
                    for model_name in models:
                        model_name = model_name.rsplit('.', 1)[-1:][0]
                        dup_sheet = copy.deepcopy(
                            sheet)  # HG: TODO: Array of Array doesn't work -- check this. data integrity impact -- consider immutable.js
                        if '*' == sheet_name:  # Change sheet name only if its '*'
                            dup_sheet.sheet_name = model_name
                        dup_sheet.dataset = _parse_dataset(dataset=copy.deepcopy(ds), model_name=model_name,
                                                           sheet_name=dup_sheet.sheet_name, ds_field=ds_field)
                        self.parsed_sheets[dup_sheet.sheet_name] = dup_sheet

                        sheet_model_map[model_name.lower()].append(
                            dup_sheet.sheet_name)  # We can have multiple sheets for same model with different filters.

                        # if ['model_names', 'model_name'] not in ds:  TODO: HG: check if none of these exists and flag error
                        #     error(name, '%s' % ds_field,
                        #           'missing \'model_name\' entry. Check mapper.datasets. '
                        #           'Note: \'model_names\' only supported with name \'*\'')
                        datakeys = [k for k in dup_sheet.dataset.data.keys()]
                        sheet_formatting = dup_sheet.formatting.copy()
                        model_fields = get_model_fields(dup_sheet.dataset.model)
                        for f in datakeys:
                            excel_dv = True if dup_sheet.dataset.data[f].references and model_fields[f].many_to_one else False
                            dup_sheet.dataset.data[f].formatting = self._get_col_formatting(f, sheet_formatting.data, excel_dv=excel_dv)
                        if 'data' in dup_sheet.formatting.data:
                            del dup_sheet.formatting.data
                        # Validate and update table formatting
                        _validate_type(sheet_name, 'formatting', dup_sheet.formatting, 'mapper.sheets')
                        dup_sheet.formatting = self._get_tbl_formatting(dup_sheet.formatting)

            except Exception as e:
                logging.error(f'Sheet [{sheet_name}], exception: [{e}]')
                print(traceback.format_exc())

        for sheet_name, sheet in self.parsed_sheets.items():  # We have case where model is referred but not exported
            # or imported
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
        #       - entry that exists in model but not defined in mapper columns col.
        #   * invalid cf fields
        #   * columns -
        #       - configure col more than 1 times using either by defining it part of 'fieldpart_*', '*', or explicitly configure for 2 times.
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
        graph = lower(self.parsed_sheets.keys())
        dfs_nodes = BoxList()

        def dfs(node):
            nonlocal visited, graph
            node = lower(node)
            if node not in visited:
                visited.add(node)
                dependents = lower(self.parsed_sheets[node].dependent_sheets)
                for neighbour in dependents:
                    dfs(neighbour)
                dfs_nodes.append(node)

        while 1:
            starting_node = set(graph) - set(visited)
            if not starting_node:
                break
            dfs(starting_node.pop())

        print(dfs_nodes)
        return dfs_nodes

    def get_sheet(self, sheet_name: str) -> Box:
        """Sheet object if name exists else None"""
        if not self._status:
            raise Exception(f'Ensure {self._file_name} is validated')

        return defval_dict(self.parsed_sheets, sheet_name, None)
        # TODO: HG: We have an issue to fix when we use filter on sample table and have multiple sheets exported and dependent sheet doesn't know how to link excel validation
        # e.g. compversion_latest and compversion_wo_latest -> use model 'componentversionmodel'
        #       compdependency depends upon model 'componentversionmodel' hence it needs to know which sheet to refer.

    def status(self):
        return self._status

    def get_errors(self):
        return self._errors
