from num2words import num2words


def transform_numbers(data):
    '''Transform numbers in words in a list or dictionary'''
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (int, float)):
                data[key] = num2words(value)
            elif isinstance(value, (list, dict)):
                transform_numbers(value)
    elif isinstance(data, list):
        for i, value in enumerate(data):
            if isinstance(value, (int, float)):
                data[i] = num2words(value)
            elif isinstance(value, (list, dict)):
                transform_numbers(value)