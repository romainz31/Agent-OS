def fahrenheit_to_celsius(fahrenheit):
    celsius = (fahrenheit - 32) * 5/9
    return celsius

def celsius_to_fahrenheit(celsius):
    fahrenheit = celsius * 9/5 + 32
    return fahrenheit

if __name__ == '__main__':
    degré = float(input('Entrez la température: '))
    conversion = input('Convertir en Fahrenheit (F) ou Celsius (C): ')
    if conversion.upper() == 'F':
        résultat = fahrenheit_to_celsius(degré)
    else:
        résultat = celsius_to_fahrenheit(degré)
    print(f'Résultat: {résultat} degrés')