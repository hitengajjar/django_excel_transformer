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
    Checks if col exists in dictionary
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

def defval_dict(dict, key, default):
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


def get_model_fields(model):
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
