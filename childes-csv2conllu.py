import csv
import re
import sys
import argparse

def csv_to_conllu(csv_file, output_stream):
    """
    Extract CoNLL-U columns from a table and adds relevant meta information from other columns.
    input: csv generated with childes.py, 1 word per row, with added CoNLL-U annotation
    output: CoNLL-U with meta information in the header of each sentence
    """
    with open(csv_file, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter='\t')
        current_sentence = []
        sentence_meta = {}

        for row in reader:
            # Detect a new sentence based on ID column
            if row['ID'] == '1' and current_sentence:
                sent_id = re.sub(r'(.*?)_w[0-9]+', r'\1', sentence_meta.get('utt_id', '')) # delete word number
                # Write the metadata
                output_stream.write(f"# sent_id = {sent_id}\n")
                output_stream.write(f"# text = {sentence_meta.get('child_project', '')}\n")
                output_stream.write(f"# speaker = {sentence_meta.get('speaker', '')}\n")
                output_stream.write(f"# child_age = {sentence_meta.get('age_days', '')}\n")
                output_stream.write(f"# child_other = {sentence_meta.get('child_other', '')}\n")
                # Write the sentence
                for line in current_sentence:
                    output_stream.write(line)
                output_stream.write("\n\n")
                current_sentence = []

            # Update sentence metadata with new sentence's info
            sentence_meta = {
                'utt_id': row['utt_id'],
                'child_project': row['child_project'],
                'speaker': row['speaker'],
                'age_days': row['age_days'],
                'child_other': row['child_other']
            }

            # Append CoNLL-U formatted word line to current sentence
            conllu_line = (
                f"{row['ID']}\t{row['FORM']}\t{row['LEMMA']}\t{row['UPOS']}\t{row['XPOS']}\t{row['FEATS']}\t"
                f"{row['HEAD']}\t{row['DEPREL']}\t{row['DEPS']}\t{row['MISC']}\n"
            )
            current_sentence.append(conllu_line)

        # Write the last sentence if it exists
        if current_sentence:
            sent_id = re.sub(r'(.*?)_w[0-9]+', r'\1', sentence_meta.get('utt_id', '')) # delete word number
            output_stream.write(f"# sent_id = {sent_id}\n")
            output_stream.write(f"# text = {sentence_meta.get('child_project', '')}\n")
            output_stream.write(f"# speaker = {sentence_meta.get('speaker', '')}\n")
            output_stream.write(f"# child_age = {sentence_meta.get('age_days', '')}\n")
            output_stream.write(f"# child_other = {sentence_meta.get('child_other', '')}\n")
            for line in current_sentence:
                output_stream.write(line)
            output_stream.write("\n")

def main():
    parser = argparse.ArgumentParser(description="Convert CSV to CoNLL-U format.")
    parser.add_argument("input_csv", help="Input CSV file with CoNLL-U data.")
    args = parser.parse_args()

    csv_to_conllu(args.input_csv, sys.stdout)

if __name__ == "__main__":
    main()
