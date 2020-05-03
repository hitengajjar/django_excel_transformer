import django
from box import Box
from collections.abc import KeysView


# from orderedset import OrderedSet


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


def val(boxv1, v2):
    """
    Returns boxv1 if it exists else returns v2
    :param boxv1:
    :param v2:
    :return:
    """
    return v2 if not boxv1 or boxv1 == Box() else boxv1


def get_attr_from_dict(box_obj, field):
    if field not in box_obj:
        raise KeyError('%s missing in %s' % (field, box_obj))
    return getattr(box_obj, field)


def getvalue(input, cls_nm):
    # TODO: HG: Need to consider various different input types
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


def get_model_fields(model, lower_case=False):
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
#
#
# def get_ref_model_fields(model_name: str, col_name: str, ref: str) -> ():
#     """ Return reference Model and Field object. In case of error return (None, None) """
#     ref_model = ref_field = None
#     if model_name and col_name and ref:
#         model = get_model(model_name)
#
#         if model:
#             model_fields = {lower(f.name): f for f in model._meta.fields + model._meta.many_to_many}
#             ref_col_name = ref.rsplit('.', 1)[-1:][0].strip().lower()
#             if ref and not model_fields[col_name].is_relation:
#                 raise AttributeError("model [%s], field [%s] isn't a reference field. mapper references: [%s]" %
#                                      (model_name, col_name, ref))
#
#             if ref.strip().split('.')[0].strip() == '$model':
#                 ref_model = model_fields[col_name].related_model
#             else:
#                 # TODO: HG: Ideally we don't need this unless we provide functionality where sheet_column_name is different from data_field
#                 #           but in that case too, we need to be able to map column_name to field_name which we don't have right now.
#                 ref_model_str = ref.rsplit('.', 2)[-2:][0].strip().lower() if len(ref.rsplit('.', 2)[-2:]) > 1 else None
#                 tmp_model = [m for m in django.apps.apps.get_models() if
#                              m._meta.model_name.lower() == ref_model_str][0] if ref_model_str else None
#
#                 ref_model = tmp_model if tmp_model == model_fields[col_name].related_model else None
#
#             if ref_model:
#                 ref_field = None
#                 for f in ref_model._meta.fields:
#                     if f.name == ref_col_name:
#                         ref_field = f
#                         break
#                 # if ref_field:
#                 #     return (ref_model, ref_field)

    # return (ref_model, ref_field)

    # Test cases
    #   model_name = [None, 'panopticum.models.modelname', 'modelname', 'something that doesn't exist']
    #   col_name = [None, 'something that doesn't exist']
    #   ref_str = [None, 'something that doesn't exist', 'models.model_name.field_name, '$model.field_name']
