import csv
import re
import argparse

def parse_csv(csv_file):
    """Parses the CSV file and returns a dictionary with unique IDs as keys and row data as values."""
    csv_data = {}

    with open(csv_file, 'r', encoding='utf-8') as f:
        # with DictReader, each row is a Dict: {'utt_id': '28167_u13272_w9', 'utt_nr': '13272', etc}
        reader = csv.DictReader(f, delimiter="\t")
        # Iterate over the rows and store the utt_id with the associated row data
        for row in reader:
            unique_id = row.get('utt_id')  # Adjust to your actual column name for ID
            if unique_id:
                csv_data[unique_id] = row
    return csv_data

def parse_csv_list(csv_file):
    """reads CSV, stores each row by ID"""
    data = {}
    with open(csv_file, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter="\t")
        #next(reader)  # Skip header
        for row in reader:
            unique_id = row[0]  # ID in first column
            data[unique_id] = row
    return data

def parse_conllu(conllu_file):
    """parses conllu, composes utterance + word ID, stores rows indexed by ID."""
    conllu_data = {}
    current_item_id = None

    with open(conllu_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#'):
                # Check if it's an item_id line, otherwise ignore it
                item_id_match = re.match(r"# item_id = (\S+)", line)
                if item_id_match:
                    current_item_id = item_id_match.group(1)
                continue

            if current_item_id and line:
                # Split the line into CoNLL-U columns
                cols = line.split('\t')
                if len(cols) >= 2:
                    word_num = cols[0]  # First column is the word index in the sentence
                    unique_id = f"{current_item_id}_w{word_num}"
                    # Store the CoNLL-U row data by the generated ID
                    conllu_data[unique_id] = cols
    return conllu_data

def enrich_conllu(conllu_file, csv_data, col_list):
    """copies columns given in col_list from the csv data to conllu"""
   
    csv_cols = col_list.split(',')  # split input list of columns
    conllu_data = []  # list, for direct output
    current_item_id = None

    with open(conllu_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            cols = line.split('\t')
            # meta line
            if line.startswith('#'):
                # get the utterance ID from meta info
                item_id_match = re.match(r"# item_id = (\S+)", line)
                if item_id_match:
                    current_item_id = item_id_match.group(1)
                conllu_data.append(cols)
                continue
            # conllu word
            elif current_item_id and line:
                if len(cols) >= 2:
                    word_num = cols[0]  # First column is the word index in the sentence
                    unique_id = f"{current_item_id}_w{word_num}"
                    csv_row = csv_data.get(unique_id)
                    if csv_row and len(cols) > 9:
                        cols[9] = get_csv_values(csv_row, csv_cols)
                conllu_data.append(cols)
            # empty line
            else:
                conllu_data.append('')  
    return conllu_data

def get_csv_values(csv_row, csv_cols):
    cat = []
    for col in csv_cols:
        try:
            csv_row[col]
        except KeyError:
            print(f"Column '{col}' doesn't exist.\nYou can use these column headers in your list:\n")
            print(csv_row.keys())
            exit(1)
        temp = f"{col}={csv_row[col]}"
        cat.append(temp)
    return '|'.join(cat)


def merge_data(csv_data, conllu_data):
    """Merges CSV and CoNLL-U data"""
    merged_data = []
    empty_conllu = [f"conll_{i}" for i in range(1, 11)]
    for unique_id, csv_row in csv_data.items():
        # Fetch the corresponding CoNLL-U row if it exists, otherwise use placeholders
        conllu_row = conllu_data.get(unique_id, empty_conllu)  # Assuming 10 fields in CoNLL-U
        merged_row = csv_row + conllu_row  # Combine CSV and CoNLL-U data
        merged_data.append(merged_row)
    return merged_data

def write_merged_output(merged_data, output_file):
    """Writes the merged data to an output file."""
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter="\t")
        for row in merged_data:
            writer.writerow(row)

def main():
    parser = argparse.ArgumentParser(description=
        '''Add CoNLL-U columns to CSV (right join).
        
        This script was written for processed CHILDES data.
        Use childes.py with option --conllu to create both files.

        '''
        )
    parser.add_argument("csv_file", help="CSV file with linguistic data")
    parser.add_argument("conllu_file", help="CoNLL-U file with parsed data")
    parser.add_argument("output_file", help="Path to output the merged file")
    
    parser.add_argument(
        '-n', '--no_merge', action='store_true',
        help='Add columns from CSV to CoNLL-U')

    parser.add_argument(
       '-e', '--enrich_conllu', default = "", type = str,
       help='Add these columns from CSV to CoNLL-U: col1,col2,...')
   
    args = parser.parse_args()

    # Read CSV data
    csv_data = parse_csv(args.csv_file)

    if args.enrich_conllu:
        # Enrich CoNLL-U data
        conllu_data = enrich_conllu(args.conllu_file, csv_data, args.enrich_conllu)
        merged_data = conllu_data
    else:
        csv_data = parse_csv_list(args.csv_file)
        # Parse CoNLL-U data
        conllu_data = parse_conllu(args.conllu_file)
        # Merge CSV and CoNLL-U data
        merged_data = merge_data(csv_data, conllu_data)

    # Write merged data to the output file
    write_merged_output(merged_data, args.output_file)
    print(f"Merged data written to {args.output_file}")

if __name__ == "__main__":
    main()