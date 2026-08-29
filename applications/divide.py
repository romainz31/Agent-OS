def divide():
    try:
        result = 10 / 0
        print(result)
    except ZeroDivisionError as e:
        print(e)

if __name__ == '__main__':
    divide()

import sys
sys.stderr.write('') # Éviter la création de l'erreur.log