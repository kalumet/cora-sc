def convert_to_minutes(time_str):
    # Definieren der Multiplikatoren für die Umrechnung in Minuten
    multipliers = {'d': 24*60, 'h': 60, 'm': 1}

    total_minutes = 0

    parts = time_str.split()

    for part in parts:
        # Extrahieren der Zahl und der Zeiteinheit
        number = int(''.join(filter(str.isdigit, part)))
        unit = ''.join(filter(str.isalpha, part))

        total_minutes += number * multipliers[unit]

    return total_minutes

# Example usage
if __name__ == "__main__":
    time_str = "1d 28h 37m"
    minutes = convert_to_minutes(time_str)
    print(f"{time_str} entspricht {minutes} Minuten.")