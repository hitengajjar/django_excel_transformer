import django
from box import Box


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


def lower_list(datalist):
    """
    Converts list string value(s) to lowercase after striping leading and trailing spaces.
    """
    lowercaselst = []
    for v in datalist:
        lowercaselst.append(v.strip().lower() if isinstance(v, str) else v)
    return lowercaselst


def lower(data):
    """
    Coverts input data string value(s) to lowercase after striping leading and trailing spaces.
    """
    if isinstance(data, dict):
        lowerdatadict = Box(default_box=True)
        for k, v in data.items():
            if isinstance(v, dict):
                lowerdatadict[k] = lower(v)
            elif isinstance(v, dict):
                lowerdatadict[k] = lower_list(v)
            elif isinstance(v, str):
                lowerdatadict[k] = v.strip().lower()
            else:
                lowerdatadict[k] = v
        return lowerdatadict
    elif isinstance(data, list):
        return lower_list(data)
    elif isinstance(data, str):
        return data.strip().lower()
    else:
        return data


def get_model_col(model_name: str):
    tmp = [m for m in django.apps.apps.get_models() if m._meta.model_name == model_name.rsplit('.', 1)[-1:][0].lower()]
    model = tmp[0] if len(tmp) == 1 else None
    model_cols = {f.name: f for f in model._meta.fields + model._meta.many_to_many} if model else None

    # Test cases:
    #   model_name = [None, 'something that doesn't exists', Django inbuilt model]
    return model, model_cols


def get_ref_model_fields(model_name: str, col_name: str, ref: str) -> ():
    """ Return reference Model and Field object. In case of error return (None, None) """
    ref_model = ref_field = None
    if model_name and col_name and ref:
        model = [m for m in django.apps.apps.get_models() if
                 m._meta.model_name == model_name.rsplit('.', 1)[-1:][0].lower()]
        if model:
            model = model[0]
            model_cols = {f.name: f for f in model._meta.fields + model._meta.many_to_many}
            ref_col_name = ref.rsplit('.', 1)[-1:][0].strip().lower()
            if ref.strip().split('.')[0].strip() == '$model':
                ref_model = model_cols[col_name].related_model
            else:
                # TODO: HG: Ideally we don't need this unless we provide functionality where sheet_column_name is different from data_field
                #           but in that case too, we need to be able to map column_name to field_name which we don't have right now.
                ref_model_str = ref.rsplit('.', 2)[-2:][0].strip().lower() if len(ref.rsplit('.', 2)[-2:]) > 1 else None
                tmp_model = [m for m in django.apps.apps.get_models() if
                     m._meta.model_name.lower() == ref_model_str][0] if ref_model_str else None


                ref_model = tmp_model if tmp_model == model_cols[col_name].related_model else None

            if ref_model:
                ref_field = None
                for f in ref_model._meta.fields:
                    if f.name == ref_col_name:
                        ref_field = f
                        break
                # if ref_field:
                #     return (ref_model, ref_field)

    return (ref_model, ref_field)


    # Test cases
    #   model_name = [None, 'panopticum.models.modelname', 'modelname', 'something that doesn't exist']
    #   col_name = [None, 'something that doesn't exist']
    #   ref_str = [None, 'something that doesn't exist', 'models.model_name.field_name, '$model.field_name']
