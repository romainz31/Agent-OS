def soustraire(a, b):
    return a - b

if __name__ == '__main__':
    a = float(input('Entrez le premier nombre: '))
    b = float(input('Entrez le second nombre: '))
    resultat = soustraire(a, b)
    print(f'Résultat: {resultat}')