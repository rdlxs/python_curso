#generar saltos con la \n
splitstring = "Prueba de como \nel \nsimbolo \nde \nbarra \ninvertida genera un scape"
print(splitstring)

#generar tabulaciones con la \t 
stringstabeadas = "1 \t2 \t3 \t4 \t5"
print(stringstabeadas)

#generar apostrofes
print('Prueba del output "Esto, eso, aquello \'e \'s, que se yo...esto es u\'n bardo" ')
print("Prueba del output \"Esto, eso, aquello 'e 's, que se yo...esto es u'n bardo\" ")
print("""Prueba del output "Esto, eso, aquello 'e 's, que se yo...esto es u'n bardo" """)

#otra forma de hacer split
otraformadesplit = """Esta es otra forma
de hacer
un split"""

print(otraformadesplit)

#delimitar la cadena de codigo
unaformamasdesplit = """Esta es otra forma \
de hacer \
un split"""

print(unaformamasdesplit)

#incluir el caracter \ en el string
#agregando otro \ al string
print("C:\\User\\max\\script.py") 

#usando r (raw) al incio del string
print(r"C:\\User\\max\\script.py") 