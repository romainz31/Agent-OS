def divide():
    try:
        result = 10 / 0
        print(result)
    except ZeroDivisionError as e:
        print('Une division par zéro a été détectée.')

divide()