def main():
    try:
        nombre1 = int(input('Saisissez le premier nombre : '))
        nombre2 = int(input('Saisissez le deuxième nombre : '))
        somme = nombre1 + nombre2
        print(f'La somme est : {somme}')
    except ValueError:
        print('Veuillez saisir des nombres valides.')

if __name__ == '__main__':
    main()