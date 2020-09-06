from enum import Enum

import django
from box import Box
from collections.abc import KeysView


class Registry:
    """
    Holds global resources
    """
    parser = None
    exporter = None
    importer = None
    config = None
    options = None
    xlwriter = None
    xlreader = None


class DBDataMistmatchError(Exception):
    """
    Exception that expresses whats wrong with DB data
    """
    def __init__(self, msg: str, **kwargs):
        self.table = kwargs["table"]
        self.filters = kwargs["filters"]
        self.value = msg

    def __str__(self):
        return "Error! Table: " + str(self.table) + ", filters: " + str(self.filters) + ", error: " + str(self.value)


def fields_exists(datadict: {}, fields: []) -> (bool, []):
    """
    Checks if field exists in dictionary
    :param datadict: source dictionary with kv
    :param fields: fields to check if they are present in dictionary
    :param exception: if
    :return: (bool, missing_fields[])
    """
    status = True
    missing = []
    for f in fields:
        if f not in datadict:
            missing.append(f)
            status = False
    return status, missing

def getdictvalue(dict, key, default):
    return dict.get(key, default) if dict else default

def val(boxv1, v2):
    return v2 if not boxv1 or boxv1 == Box() else boxv1


def get_attr_from_dict(box_obj, field):
    if field not in box_obj:
        raise KeyError('%s missing in %s' % (field, box_obj))
    return getattr(box_obj, field)


def getvalue(input, cls_nm):
    # TODO: HG: Need to consider various input types
    return cls_nm(input)


def nm(class_name) -> str:
    """
    Helper function to return string name of class
    :param class_name:
    :return: str version of class_name
    """
    if not class_name:
        return 'None'
    if isinstance(class_name, str):
        return class_name
    else:
        return class_name.__name__


def lower(data):
    """
    Utility function. Coverts input data string value(s) to lowercase after striping leading and trailing spaces.
    """
    if isinstance(data, dict):
        lowerdatadict = Box(default_box=True)
        for k, v in data.items():
            lowerdatadict[k] = lower(v)
        return lowerdatadict
    elif isinstance(data, list):
        lowercaselst = []
        for v in data:
            lowercaselst.append(lower(v))
        return lowercaselst
    elif isinstance(data, KeysView) or isinstance(data, set):
        lowercaseset = set()
        for v in data:
            lowercaseset.add(lower(v))
        return lowercaseset
    elif isinstance(data, str):
        return data.strip().lower()
    else:
        return data


def get_model_fields(model: object) -> object:
    # if not lower_case:
    model_fields = {f.name: f for f in model._meta.fields + model._meta.many_to_many} if model else None
    # else:
    #     model_fields = {lower(f.name): f for f in model._meta.fields + model._meta.many_to_many} if model else None

    # Test cases:
    #   model_name = [None, 'something that doesn't exists', Django inbuilt model]
    return model_fields


def get_model(model_name: str):
    """
    Fetch model object given model_name.
    :param model_name: name of model
    :return: model object
    :raises: ValueError if model_name doesn't exists
    """
    if not model_name:
        raise ValueError("model [None] not supported")

    model = [m for m in django.apps.apps.get_models() if
             lower(m._meta.model_name) == lower(model_name.rsplit('.', 1)[-1:][0])]
    if not model:
        raise ValueError("model [%s] doesn't exist" % model_name)

    return model[0]



class Issue(Enum):
    EQUAL = 'equal'
    NONE = 'none'
    MAJOR = 'major'
    MINOR = 'minor'


class ColumnCompare:  # Column level only if conflict at column level
    def __init__(self, issue: Issue, msg: str, field, xlsvalue, dbvalue, ref_sheet=None):
        self.issue = issue
        self.msg = msg  # Mostly will be empty but used in case of exception scenarios
        self.field = field  # e.g. life_status, category
        self.xlsvalue = xlsvalue
        self.dbvalue = dbvalue  # value found in DB
        self.ref_sheet = ref_sheet  # Reference to Worksheet for col source

    # def __str__(self):
    #     return json.dumps(self, default=lambda o: [i if not isinstance(Issue, i) else None for i in o.__dict__],
    #                       sort_keys=True, indent=4)


class RowResult:  # Row level Result
    def __init__(self, msg: str, col: ColumnCompare):
        self.msg = msg
        self.cols: [ColumnCompare] = []
        self.cols.append(col)


class Records:  # Table level records
    def __init__(self):
        self.db = {}  # dict(index=dbobj) so each db table row has one dict entry
        self.xls = {}  # dict(index=dict(of xls rows) so each xls table row has one dict entry
        self.status = {}  # dict(index=[RowResult]) so each row represents either db table row or xls table row


def get_references(model_name, field, references):
    """
    Validates and provides valid reference fields. In case of invalid fields will throw AttributeError. If
    wrong models are referenced then will throw ValueError
    :param model_name: model name
    :param field: field name
    :param references: list of reference
    :return:
    """
    ref_data = []
    model = get_model(model_name)
    fields = get_model_fields(model)
    django_field_nm = [tmp for tmp in fields if lower(field) == lower(tmp)]
    # need exact field name for de-referencing within Django model
    if not django_field_nm:
        raise AttributeError(f'model [{model_name}] doesnt have field [{django_field_nm}]')

    django_field_nm = django_field_nm[0]

    if references and not model._meta.get_field(django_field_nm).is_relation:
        raise AttributeError(
            f'model [{model_name}], field [{django_field_nm}] isnt a reference field. mapper references: [{references}]')
    elif model._meta.get_field(django_field_nm).is_relation and not references:
        references = ["$model.id"]  # Lets add ref by ourselves, eases export and importer

    for ref in references:
        ref_field = ref.split('.', 1)[1] if ref[0] == '$' else ref
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
                raise ValueError(
                    f'Invalid model [{ref_model_str}] expected [{model._meta.get_field(django_field_nm).related_model}]')


        if ref_field != 'id':
            for f in ref_field.split('.'):
                try:
                    dbfield = [mf for mf in get_model_fields(ref_model).keys() if lower(mf) == lower(f)][0]
                    ref_model = get_model_fields(ref_model)[dbfield].related_model
                except KeyError as e:
                    raise ValueError(
                        f'Invalid reference_field [{ref_field}] for field [{django_field_nm}], model [{model_name}]. Exception: {e}')
            if not dbfield:
                raise ValueError(f'Invalid reference_field [{ref_field}] for field [{django_field_nm}], model [{model_name}]')
        ref_data.append((ref_model_str, ref_field))
    return ref_data