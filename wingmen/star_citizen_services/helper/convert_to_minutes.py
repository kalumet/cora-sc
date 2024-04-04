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


def convert_to_str(seconds):   
    # Berechnung der Tage, Stunden und Minuten
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    
    # Erstellung des formatierten Strings, ohne Werte gleich 0 auszugeben
    time_parts = []
    if days > 0:
        time_parts.append(f"{days}d")
    if hours > 0:
        time_parts.append(f"{hours}h")
    if minutes > 0:
        time_parts.append(f"{minutes}m")
    
    # Zusammenfügen der Zeitteile zu einem String, Trennzeichen ist ein Leerzeichen
    formatted_time = " ".join(time_parts)
    
    # Rückgabe des formatierten Strings, oder "0m", falls alle Teile 0 sind
    return formatted_time if formatted_time else "completed"

# Example usage
if __name__ == "__main__":
    time_str = "1d 28h 37m"
    minutes = convert_to_minutes(time_str)
    print(f"{time_str} entspricht {minutes} Minuten.")