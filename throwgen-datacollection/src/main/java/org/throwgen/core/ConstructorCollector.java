package org.throwgen.core;

import java.io.FileWriter;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Modifier;
import java.lang.reflect.Parameter;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Paths;

public class ConstructorCollector {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            throw new IllegalArgumentException("Premain needs 2 arguments");
        }

        String className = args[0];
        String outPath = args[1];

        Class<?> clazz = Class.forName(className);

        // Get all constructors
        Constructor<?>[] constructors = clazz.getDeclaredConstructors();
        FileWriter outFile = new FileWriter(outPath);

        for (Constructor<?> constructor : constructors) {
            outFile.write(constructorToString((constructor)) + "\n");
        }
        outFile.close();
    }

    private static String constructorToString(Constructor<?> constructor) {
        StringBuilder sb = new StringBuilder();

        // Add modifiers (public, private, etc.)
        sb.append(Modifier.toString(constructor.getModifiers()));
        if (sb.length() > 0)
            sb.append(" ");

        // Add constructor name
        sb.append(constructor.getName().substring(
            constructor.getName().lastIndexOf('.') + 1));

        // Add parameters
        sb.append("(");
        Parameter[] parameters = constructor.getParameters();
        for (int i = 0; i < parameters.length; i++) {
            if (i > 0)
                sb.append(", ");
            Parameter param = parameters[i];
            sb.append(param.getType().getSimpleName());

            // Add parameter name if available
            if (param.isNamePresent()) {
                sb.append(" ").append(param.getName());
            } else {
                sb.append(" arg").append(i); // Fallback if name not available
            }
        }

        sb.append(")");

        // Add exceptions
        Class<?>[] exceptionTypes = constructor.getExceptionTypes();
        if (exceptionTypes.length > 0) {
            sb.append(" throws ");
            for (int i = 0; i < exceptionTypes.length; i++) {
                if (i > 0)
                    sb.append(", ");
                sb.append(exceptionTypes[i].getSimpleName());
            }
        }

        return sb.toString();
    }
}
