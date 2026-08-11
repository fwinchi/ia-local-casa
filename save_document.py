def save_document(content, filename):
    with open(filename, 'w') as file:
        file.write(content)

# Ejemplo de uso
document_content = "Este es el contenido del documento."
file_name = "mi_documento.txt"
save_document(document_content, file_name)
